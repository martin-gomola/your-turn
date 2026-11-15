"""One shared background inbox, controlled through its private shutdown token."""

from __future__ import annotations

import errno
import http.client
import json
import os
import secrets
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

WAIT_SECONDS = 5.0


def default_state_dir() -> Path:
    return Path.home() / ".your-turn"


@contextmanager
def _connection(port: int, timeout: float) -> Iterator[http.client.HTTPConnection]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    expired = threading.Event()
    timer = None
    try:
        deadline = time.monotonic() + timeout
        connection.connect()
        transport = connection.sock

        def interrupt() -> None:
            expired.set()
            try:
                transport.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

        timer = threading.Timer(max(0, deadline - time.monotonic()), interrupt)
        timer.daemon = True
        timer.start()
        yield connection
        if expired.is_set():
            raise TimeoutError(f"request exceeded {timeout:g}s")
    except (OSError, http.client.HTTPException, ValueError) as error:
        if expired.is_set():
            raise TimeoutError(f"request exceeded {timeout:g}s") from error
        raise
    finally:
        if timer is not None:
            timer.cancel()
        connection.close()


def probe(port: int, timeout: float = 0.5) -> dict[str, Any] | None:
    """Return a verified identity; only a refused connection means no server."""
    if type(port) is not int or not 1 <= port <= 65535:
        raise RuntimeError("The inbox port must be between 1 and 65535.")
    try:
        with _connection(port, timeout) as connection:
            connection.request("GET", "/api/health")
            response = connection.getresponse()
            if response.status != 200:
                raise RuntimeError(f"Port {port} did not return Your Turn health (HTTP {response.status}).")
            raw = response.read(4097)
            if len(raw) > 4096:
                raise ValueError("health response is too large")
            identity = json.loads(raw)
        if (not isinstance(identity, dict) or identity.get("app") != "your-turn"
                or not isinstance(identity.get("version"), str) or not identity["version"]
                or type(identity.get("pid")) is not int or identity["pid"] <= 0
                or "instance" not in identity
                or identity["instance"] is not None and (not isinstance(identity["instance"], str) or not identity["instance"])):
            raise ValueError("unexpected health identity")
        return identity
    except ConnectionRefusedError:
        return None
    except (OSError, http.client.HTTPException, ValueError) as error:
        raise RuntimeError(f"Cannot verify Your Turn on port {port}: {error}") from error


def _directory(path: Path) -> Path:
    path = path.expanduser().absolute()
    if path.is_symlink():
        raise RuntimeError(f"Refusing a symlinked server state directory: {path}")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or os.name != "nt" and (info.st_uid != os.getuid() or info.st_mode & 0o022):
        raise RuntimeError(f"Server state directory must be private to your user: {path}")
    return path


def _open(path: Path, flags: int) -> int:
    if path.is_symlink():
        raise RuntimeError(f"Refusing a symlinked server control file: {path}")
    descriptor = None
    try:
        descriptor = os.open(path, flags | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0), 0o600)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("expected a regular private file")
        if hasattr(os, "fchmod"):
            os.fchmod(descriptor, 0o600)
        return descriptor
    except (OSError, ValueError) as error:
        if descriptor is not None:
            os.close(descriptor)
        raise RuntimeError(f"Cannot access server control file {path}: {error}") from error


@contextmanager
def _locked(path: Path) -> Iterator[Path]:
    root = _directory(path)
    with os.fdopen(_open(root / "server.lock", os.O_RDWR | os.O_CREAT), "r+b", buffering=0) as lock:
        if os.name == "nt":
            import msvcrt

            if not lock.read(1):
                lock.write(b"\0")
        else:
            import fcntl

        deadline = time.monotonic() + WAIT_SECONDS
        while True:
            try:
                if os.name == "nt":
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() >= deadline:
                    raise RuntimeError("Another Your Turn start or stop is still in progress.") from error
                time.sleep(0.05)
        yield root


def _read_state(root: Path) -> dict[str, Any] | None:
    path = root / "server.json"
    if path.is_symlink():
        raise RuntimeError(f"Refusing a symlinked server control file: {path}")
    if not path.exists():
        return None
    try:
        with os.fdopen(_open(path, os.O_RDONLY)) as handle:
            state = json.load(handle)
        if (not isinstance(state, dict) or type(state.get("pid")) is not int or state["pid"] <= 0
                or type(state.get("port")) is not int or not 1 <= state["port"] <= 65535
                or not isinstance(state.get("instance"), str) or not state["instance"]
                or not isinstance(state.get("token"), str) or not state["token"]):
            raise ValueError("unexpected state fields")
        return state
    except (OSError, ValueError) as error:
        raise RuntimeError(f"Invalid server state in {path}: {error}") from error


def _write_state(root: Path, state: dict[str, Any]) -> None:
    descriptor, name = tempfile.mkstemp(prefix=".server-", dir=root)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(state, handle)
            handle.flush()
            os.fsync(handle.fileno())
        if (root / "server.json").is_symlink():
            raise RuntimeError("Refusing a symlinked server control file: server.json")
        os.replace(name, root / "server.json")
    finally:
        Path(name).unlink(missing_ok=True)


def _matches(identity: dict[str, Any], state: dict[str, Any]) -> bool:
    return identity["pid"] == state["pid"] and identity["instance"] == state["instance"]


def _remove_state(root: Path, state: dict[str, Any]) -> None:
    if _read_state(root) == state:
        (root / "server.json").unlink()


def _reap_failed_start(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)


def start(port: int = 8787, state_dir: Path | None = None, serve_args: Sequence[str] = ()) -> dict[str, Any]:
    """Reuse a verified inbox or start one detached from the caller's terminal."""
    with _locked(state_dir if state_dir is not None else default_state_dir()) as root:
        state = _read_state(root)
        if state and state["port"] != port:
            previous = probe(state["port"])
            if previous and _matches(previous, state):
                raise RuntimeError(f"Your Turn is already managed on port {state['port']}; stop it before changing ports.")
        identity = probe(port)
        if identity:
            return identity
        state = {"port": port, "instance": secrets.token_hex(16), "token": secrets.token_urlsafe(32)}
        env = {**os.environ, "YOUR_TURN_INSTANCE": state["instance"], "YOUR_TURN_STOP_TOKEN": state["token"],
               "YOUR_TURN_STATE_DIR": str(root)}
        process = None
        try:
            with os.fdopen(_open(root / "server.log", os.O_WRONLY | os.O_CREAT | os.O_APPEND), "ab") as log:
                process = subprocess.Popen(
                    [sys.executable, "-I", "-m", "yourturn", "serve", "--managed", "--port", str(port), *serve_args],
                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, cwd=root, env=env,
                    start_new_session=os.name != "nt",
                    creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0,
                )
            state["pid"] = process.pid
            _write_state(root, state)
            deadline = time.monotonic() + WAIT_SECONDS
            while time.monotonic() < deadline:
                identity = probe(port)
                if identity:
                    if not _matches(identity, state):
                        _reap_failed_start(process)
                        _remove_state(root, state)
                    return identity
                if process.poll() is not None:
                    raise RuntimeError(f"Your Turn exited during startup; see {root / 'server.log'}.")
                time.sleep(0.05)
            raise RuntimeError(f"Your Turn did not become ready within {WAIT_SECONDS:g}s; see {root / 'server.log'}.")
        except Exception:
            if process is not None:
                _reap_failed_start(process)
                _remove_state(root, state)
            raise


def stop(state_dir: Path | None = None) -> bool:
    """Stop only the managed instance whose private control record still matches."""
    path = state_dir if state_dir is not None else default_state_dir()
    if not path.exists() and not path.is_symlink():
        return False
    with _locked(path) as root:
        state = _read_state(root)
        if state is None:
            return False
        identity = probe(state["port"])
        if identity is None or not _matches(identity, state):
            _remove_state(root, state)
            return False
        try:
            with _connection(state["port"], 1) as connection:
                connection.request("POST", "/api/shutdown", headers={"X-Your-Turn-Token": state["token"]})
                response = connection.getresponse()
                if response.status not in (200, 202, 204):
                    raise RuntimeError(f"Your Turn refused shutdown (HTTP {response.status}); control state retained.")
        except (OSError, http.client.HTTPException) as error:
            raise RuntimeError(f"Could not request Your Turn shutdown: {error}") from error
        deadline = time.monotonic() + WAIT_SECONDS
        while time.monotonic() < deadline:
            try:
                identity = probe(state["port"])
            except RuntimeError as error:
                if not isinstance(error.__cause__, (OSError, http.client.HTTPException)):
                    raise
            else:
                if identity is None or not _matches(identity, state):
                    _remove_state(root, state)
                    return True
            time.sleep(0.05)
        raise RuntimeError(f"Your Turn did not stop within {WAIT_SECONDS:g}s; control state retained.")
