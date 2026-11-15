import json
import os
import shlex
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from yourturn import autostart


def test_enable_is_idempotent_and_keeps_the_exact_python_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "Codex profile"
    state = tmp_path / "state with $dollar and 'quote'"
    executable = tmp_path / "venv with spaces" / "python"
    executable.parent.mkdir()
    executable.symlink_to(sys.executable)
    monkeypatch.setattr(sys, "executable", str(executable))

    assert "unverified" in autostart.enable(home, state)
    path = home / "hooks.json"
    saved, inode = path.read_bytes(), path.stat().st_ino
    data = json.loads(saved)
    group = data["hooks"]["SessionStart"][0]
    handler = group["hooks"][0]
    assert group["matcher"] == "*"
    assert shlex.split(handler["command"]) == [str(executable), "-I", "-m", "yourturn.autostart", "run",
                                                "--codex-home", str(home), "--state-dir", str(state), "--port", "8787"]
    assert handler["async"] is True and handler["timeout"] == 10
    assert "interpreter found" in autostart.status(home)
    assert "unverified" in autostart.status(home)
    autostart.enable(home, state)
    assert path.read_bytes() == saved and path.stat().st_ino == inode
    assert list(home.iterdir()) == [path]


def test_reenable_refreshes_a_missing_runtime_and_state_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "codex"
    monkeypatch.setattr(sys, "executable", str(tmp_path / "evicted-cache" / "python"))
    autostart.enable(home, tmp_path / "old-state")
    assert "runtime missing" in autostart.status(home)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "new-runtime" / "python"))
    autostart.enable(home, tmp_path / "new-state", port=9123)
    groups = json.loads((home / "hooks.json").read_text())["hooks"]["SessionStart"]
    assert len(groups) == 1 and len(groups[0]["hooks"]) == 1
    command = shlex.split(groups[0]["hooks"][0]["command"])
    assert command[0] == str(tmp_path / "new-runtime" / "python")
    assert command[8] == str(tmp_path / "new-state")
    assert command[9:] == ["--port", "9123"]


@pytest.mark.parametrize("port", [-1, 0, 65536, "8787", True])
def test_enable_rejects_invalid_port_before_writing(tmp_path: Path, port: object) -> None:
    home = tmp_path / "codex"
    with pytest.raises(ValueError, match="port must be an integer between"):
        autostart.enable(home, tmp_path / "state", port=port)
    assert not home.exists()


def test_disable_preserves_other_handlers_groups_and_metadata(tmp_path: Path) -> None:
    home = tmp_path / "codex"
    home.mkdir()
    path = home / "hooks.json"
    other = {"type": "command", "command": "echo user-hook", "statusMessage": "User hook"}
    original = {"description": "My hooks", "custom": {"keep": True},
                "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo stop"}]}],
                          "SessionStart": [{"matcher": "resume", "hooks": [other]}]}}
    path.write_text(json.dumps(original))
    autostart.enable(home, tmp_path / "state")
    data = json.loads(path.read_text())
    data["hooks"]["SessionStart"][-1]["description"] = "Keep my group metadata"
    data["hooks"]["SessionStart"][-1]["hooks"].append({"type": "command", "command": "echo shared"})
    path.write_text(json.dumps(data))

    autostart.disable(home)

    expected = original
    expected["hooks"]["SessionStart"].append({"matcher": "*", "description": "Keep my group metadata",
                                               "hooks": [{"type": "command", "command": "echo shared"}]})
    assert json.loads(path.read_text()) == expected
    before = path.read_bytes()
    autostart.disable(home)
    assert path.read_bytes() == before


def test_disable_does_not_remove_a_command_with_an_injected_suffix(tmp_path: Path) -> None:
    home = tmp_path / "codex"
    autostart.enable(home, tmp_path / "state")
    path = home / "hooks.json"
    data = json.loads(path.read_text())
    data["hooks"]["SessionStart"][0]["hooks"][0]["command"] += "; echo not-ours"
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    assert "modified and retained" in autostart.status(home)
    for action in (autostart.enable, autostart.disable):
        with pytest.raises(ValueError, match="modified and retained"):
            action(home)
        assert path.read_bytes() == before


def test_modified_candidate_blocks_changes_even_beside_an_owned_handler(tmp_path: Path) -> None:
    home = tmp_path / "codex"
    autostart.enable(home, tmp_path / "state")
    path = home / "hooks.json"
    data = json.loads(path.read_text())
    handlers = data["hooks"]["SessionStart"][0]["hooks"]
    handlers.append({**handlers[0], "command": "echo user-modified-hook"})
    path.write_text(json.dumps(data))
    before = path.read_bytes()
    assert "modified and retained" in autostart.status(home)
    for action in (autostart.enable, autostart.disable):
        with pytest.raises(ValueError, match="modified and retained"):
            action(home)
        assert path.read_bytes() == before


def test_disable_removes_only_its_own_empty_config(tmp_path: Path) -> None:
    home = tmp_path / "codex"
    assert autostart.status(home) == "autostart disabled"
    assert not home.exists()
    autostart.enable(home, tmp_path / "state")
    autostart.disable(home)
    assert not (home / "hooks.json").exists()
    (home / "hooks.json").write_text("{}\n")
    autostart.disable(home)
    assert (home / "hooks.json").read_text() == "{}\n"


@pytest.mark.parametrize("raw", ["{", "[]", '{"hooks": []}', '{"hooks": {"SessionStart": "bad"}}',
                               '{"hooks": {"SessionStart": [{"hooks": ["bad"]}]}}'])
def test_malformed_config_is_never_overwritten(tmp_path: Path, raw: str) -> None:
    home = tmp_path / "codex"
    home.mkdir()
    path = home / "hooks.json"
    path.write_text(raw)
    for action in (autostart.enable, autostart.disable, autostart.status):
        with pytest.raises(ValueError):
            action(home)
        assert path.read_text() == raw


def test_symlink_config_and_profile_are_rejected(tmp_path: Path) -> None:
    target = tmp_path / "user-hooks.json"
    target.write_text('{"description": "untouched"}')
    home = tmp_path / "codex"
    home.mkdir()
    (home / "hooks.json").symlink_to(target)
    for action in (autostart.enable, autostart.disable, autostart.status):
        with pytest.raises(ValueError):
            action(home)
    assert target.read_text() == '{"description": "untouched"}'
    link = tmp_path / "profile-link"
    link.symlink_to(home, target_is_directory=True)
    with pytest.raises(ValueError):
        autostart.enable(link)


@pytest.mark.parametrize("unsafe", ["permissions", "hardlink", "directory"])
def test_unsafe_config_is_rejected(tmp_path: Path, unsafe: str) -> None:
    home = tmp_path / "codex"
    home.mkdir()
    path = home / "hooks.json"
    if unsafe == "directory":
        path.mkdir()
    else:
        path.write_text("{}")
        if unsafe == "permissions":
            path.chmod(0o666)
        else:
            os.link(path, home / "linked.json")
    with pytest.raises(ValueError):
        autostart.enable(home)


def test_failed_atomic_update_keeps_the_original_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "codex"
    home.mkdir()
    path = home / "hooks.json"
    path.write_text('{"description":"keep formatting and data"}')
    before = path.read_bytes()

    def fail(*args: object) -> None:
        raise OSError("disk error")

    monkeypatch.setattr(autostart.os, "replace", fail)
    with pytest.raises(OSError, match="disk error"):
        autostart.enable(home, tmp_path / "state")
    assert path.read_bytes() == before
    assert list(home.iterdir()) == [path]


def test_concurrent_config_change_is_preserved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "codex"
    home.mkdir()
    path = home / "hooks.json"
    path.write_text("{}")
    concurrent = '{"description": "changed elsewhere"}'
    fsync = os.fsync

    def change_config(descriptor: int) -> None:
        fsync(descriptor)
        path.write_text(concurrent)

    monkeypatch.setattr(autostart.os, "fsync", change_config)
    with pytest.raises(ValueError, match="changed during setup"):
        autostart.enable(home, tmp_path / "state")
    assert path.read_text() == concurrent
    assert list(home.iterdir()) == [path]


def test_hook_starts_the_selected_profile_without_stdout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                       capsys: pytest.CaptureFixture[str]) -> None:
    calls = []

    def start(**kwargs: object) -> str:
        calls.append(kwargs)
        print("server output")
        return "started"

    monkeypatch.setitem(sys.modules, "yourturn.server", SimpleNamespace(start=start))
    home, state = tmp_path / "codex", tmp_path / "state"
    assert autostart.main(["run", "--codex-home", str(home), "--state-dir", str(state), "--port", "9123"]) == 0
    assert calls == [{"port": 9123, "state_dir": state, "serve_args": ["--codex-home", str(home)]}]
    assert capsys.readouterr() == ("", "")
    assert "server output" in (state / "autostart.log").read_text()


def test_hook_failure_is_logged_and_never_blocks_codex(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                     capsys: pytest.CaptureFixture[str]) -> None:
    def fail(**kwargs: object) -> None:
        raise OSError("cannot launch inbox")

    monkeypatch.setitem(sys.modules, "yourturn.server", SimpleNamespace(start=fail))
    state = tmp_path / "state"
    assert autostart.main(["run", "--codex-home", str(tmp_path / "codex"), "--state-dir", str(state)]) == 0
    assert capsys.readouterr() == ("", "")
    assert "cannot launch inbox" in (state / "autostart.log").read_text()


def test_hook_does_not_follow_a_log_symlink(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                          capsys: pytest.CaptureFixture[str]) -> None:
    state = tmp_path / "state"
    state.mkdir()
    target = tmp_path / "user-file"
    target.write_text("untouched")
    (state / "autostart.log").symlink_to(target)
    calls = []
    monkeypatch.setitem(sys.modules, "yourturn.server", SimpleNamespace(start=lambda **kwargs: calls.append(kwargs)))
    assert autostart.main(["run", "--codex-home", str(tmp_path / "codex"), "--state-dir", str(state)]) == 0
    assert not calls and target.read_text() == "untouched"
    output = capsys.readouterr()
    assert output.out == "" and "could not write" in output.err and "symlink" in output.err


def test_hook_log_permission_failure_has_a_native_stderr_diagnostic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                                                  capsys: pytest.CaptureFixture[str]) -> None:
    def denied(*args: object) -> int:
        raise PermissionError("log is not writable")

    monkeypatch.setattr(autostart.os, "open", denied)
    assert autostart.main(["run", "--codex-home", str(tmp_path / "codex"), "--state-dir", str(tmp_path / "state")]) == 0
    output = capsys.readouterr()
    assert output.out == "" and "could not write" in output.err and "log is not writable" in output.err
