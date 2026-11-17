from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from yourturn import server


@contextmanager
def health_server(identity, status=200, shutdown_status=403, close_after_shutdown=False):
    requests = []
    closing = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            requests.append(("GET", self.path))
            if close_after_shutdown and any(method == "POST" for method, _ in requests) and not closing.is_set():
                closing.set()
                self.connection.shutdown(socket.SHUT_RDWR)

                def close_listener():
                    httpd.shutdown()
                    httpd.server_close()

                threading.Thread(target=close_listener, daemon=True).start()
                return
            self.send_response(status)
            self.end_headers()
            self.wfile.write(json.dumps(identity).encode())

        def do_POST(self):
            requests.append(("POST", self.headers.get("X-Your-Turn-Token")))
            self.send_response(shutdown_status)
            self.end_headers()

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield httpd.server_port, requests
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def identity(instance="managed"):
    return {"app": "your-turn", "version": "test", "pid": 12345, "instance": instance}


def owned_state(root: Path, port: int, **changes):
    root.mkdir(mode=0o700)
    state = {"pid": 12345, "port": port, "instance": "managed", "token": "private-token", **changes}
    path = root / "server.json"
    path.write_text(json.dumps(state))
    return path


def test_probe_only_refused_connection_means_absent():
    assert server.probe(free_port()) is None
    with health_server(identity()) as (port, requests):
        assert server.probe(port) == identity()
        assert requests == [("GET", "/api/health")]


@pytest.mark.parametrize(("body", "status"), [({"app": "other"}, 200), (identity(), 302),
                                             ({**identity(), "pid": True}, 200),
                                             ({k: v for k, v in identity().items() if k != "instance"}, 200)])
def test_probe_rejects_foreign_or_invalid_health(body, status):
    with health_server(body, status) as (port, requests):
        with pytest.raises(RuntimeError):
            server.probe(port)
        assert requests == [("GET", "/api/health")]


@pytest.mark.parametrize("slow_part", ["headers", "body"])
def test_probe_deadline_bounds_trickling_responses(slow_part):
    body = json.dumps(identity()).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            try:
                if slow_part == "headers":
                    self.wfile.write(b"HTTP/1.0 200 OK\r\n")
                    payload = f"Content-Length: {len(body)}\r\n\r\n".encode() + body
                else:
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    payload = body
                for byte in payload:
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
                    time.sleep(0.03)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *args):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        started = time.monotonic()
        with pytest.raises(RuntimeError, match="exceeded"):
            server.probe(httpd.server_port, timeout=0.1)
        assert time.monotonic() - started < 1
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def test_start_reuses_manual_server_without_claiming_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(server.subprocess, "Popen", lambda *a, **kw: pytest.fail("Should reuse the server"))
    with health_server(identity(None)) as (port, requests):
        root = tmp_path / "state"
        assert server.start(port, root) == identity(None)
        assert not (root / "server.json").exists()
        assert not server.stop(root)
        assert requests == [("GET", "/api/health")]


@pytest.mark.parametrize("field", ["pid", "instance"])
def test_stop_does_not_touch_a_different_instance(tmp_path: Path, field):
    with health_server(identity()) as (port, requests):
        path = owned_state(tmp_path / "state", port, **{field: 999 if field == "pid" else "stale"})
        assert not server.stop(path.parent)
        assert not path.exists()
        assert requests == [("GET", "/api/health")]


def test_stop_sends_private_token_and_retains_rejected_state(tmp_path: Path):
    with health_server(identity()) as (port, requests):
        path = owned_state(tmp_path / "state", port)
        with pytest.raises(RuntimeError, match="refused shutdown"):
            server.stop(path.parent)
        assert path.exists()
        assert requests[-1] == ("POST", "private-token")


def test_stop_waits_through_listener_close_after_accepted_shutdown(tmp_path: Path):
    with health_server(identity(), shutdown_status=204, close_after_shutdown=True) as (port, requests):
        path = owned_state(tmp_path / "state", port)
        assert server.stop(path.parent)
        assert not path.exists()
        assert [request for request in requests if request[0] == "POST"] == [("POST", "private-token")]


def test_stop_keeps_unverified_server_untouched_before_shutdown(tmp_path: Path):
    with health_server({"app": "other"}) as (port, requests):
        path = owned_state(tmp_path / "state", port)
        with pytest.raises(RuntimeError, match="Cannot verify"):
            server.stop(path.parent)
        assert path.exists()
        assert requests == [("GET", "/api/health")]


def test_stop_retains_state_if_transport_never_confirms_shutdown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with health_server(identity(), shutdown_status=204) as (port, requests):
        path = owned_state(tmp_path / "state", port)
        original_probe = server.probe

        def failing_after_shutdown(port):
            if any(method == "POST" for method, _ in requests):
                raise RuntimeError("connection reset") from ConnectionResetError("listener is closing")
            return original_probe(port)

        monkeypatch.setattr(server, "probe", failing_after_shutdown)
        monkeypatch.setattr(server, "WAIT_SECONDS", 0.01)
        with pytest.raises(RuntimeError, match="did not stop"):
            server.stop(path.parent)
        assert path.exists()
        assert [request for request in requests if request[0] == "POST"] == [("POST", "private-token")]


def test_start_will_not_orphan_a_managed_server_on_another_port(tmp_path: Path):
    with health_server(identity()) as (port, _):
        path = owned_state(tmp_path / "state", port)
        before = path.read_bytes()
        with pytest.raises(RuntimeError, match="already managed"):
            server.start(free_port(), path.parent)
        assert path.read_bytes() == before


@pytest.mark.parametrize("name", ["server.lock", "server.json", "server.log"])
def test_start_refuses_symlinked_control_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name):
    root = tmp_path / "state"
    root.mkdir(mode=0o700)
    target = tmp_path / "keep.txt"
    target.write_text("keep me")
    (root / name).symlink_to(target)
    monkeypatch.setattr(server.subprocess, "Popen", lambda *a, **kw: pytest.fail("Unsafe startup"))
    with pytest.raises(RuntimeError, match="symlink"):
        server.start(free_port(), root)
    assert target.read_text() == "keep me"


@pytest.mark.skipif(not hasattr(os, "fchmod"), reason="File-descriptor permissions are POSIX-only")
def test_control_file_permission_failure_closes_its_descriptor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    descriptors = []

    def fail(descriptor, mode):
        descriptors.append(descriptor)
        raise PermissionError("cannot make the control file private")

    monkeypatch.setattr(server.os, "fchmod", fail)
    with pytest.raises(RuntimeError, match="control file"):
        server.start(free_port(), tmp_path / "state")
    with pytest.raises(OSError):
        os.fstat(descriptors[0])


def test_failed_start_reaps_its_own_child_and_preserves_interpreter(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    launched = {}

    class Process:
        pid = 12345
        returncode = None

        def __init__(self, args, **kwargs):
            launched.update(args=args, **kwargs)

        def poll(self):
            return self.returncode

        def terminate(self):
            launched["terminated"] = True

        def wait(self, timeout):
            self.returncode = 0

    executable = str(tmp_path / "venv" / "bin" / "python")
    monkeypatch.setattr(server.sys, "executable", executable)
    monkeypatch.setattr(server.subprocess, "Popen", Process)
    monkeypatch.setattr(server, "probe", lambda port: None)
    monkeypatch.setattr(server, "WAIT_SECONDS", 0.01)
    with pytest.raises(RuntimeError, match="did not become ready"):
        server.start(8787, tmp_path / "state", ("--phone",))
    assert launched["args"] == [executable, "-I", "-m", "yourturn", "serve", "--managed", "--port", "8787", "--phone"]
    assert launched["terminated"]
    assert not (tmp_path / "state" / "server.json").exists()


def test_concurrent_processes_share_one_server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root, port = tmp_path / "state", free_port()
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    (shadow / "yourturn.py").write_text('raise RuntimeError("ambient path shadowed the installed package")\n')
    monkeypatch.setenv("PYTHONPATH", str(shadow))
    script = ("import json,sys; from pathlib import Path; from yourturn.server import start; "
              "print(json.dumps(start(int(sys.argv[2]), Path(sys.argv[1]))))")
    callers = [subprocess.Popen([sys.executable, "-I", "-c", script, str(root), str(port)], cwd=tmp_path,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    try:
        results = []
        for caller in callers:
            out, error = caller.communicate(timeout=15)
            assert caller.returncode == 0, error
            results.append(json.loads(out))
        assert results[0] == results[1]
        state = json.loads((root / "server.json").read_text())
        assert state["pid"] == results[0]["pid"] and state["instance"] == results[0]["instance"]
        assert state["token"] and state["port"] == port
        if os.name != "nt":
            assert (root / "server.json").stat().st_mode & 0o777 == 0o600
        assert server.stop(root)
        assert server.probe(port) is None
        assert not (root / "server.json").exists()
    finally:
        for caller in callers:
            if caller.poll() is None:
                caller.terminate()
                caller.wait(timeout=5)
        server.stop(root)
