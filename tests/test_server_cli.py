import json
import subprocess
import sys

import pytest

from yourturn import server
from yourturn.cli import main


def test_start_forwards_profile_and_phone_settings(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(server, "start", lambda *args: calls.append(args) or {"pid": 123})
    main(["start", "--port", "9001", "--state-dir", str(tmp_path / "state"),
          "--codex-home", str(tmp_path / "codex"), "--claude-home", str(tmp_path / "claude"),
          "--cursor-home", str(tmp_path / "cursor"), "--cursor-user-dir", str(tmp_path / "user"), "--phone"])
    assert calls == [(9001, tmp_path / "state", ["--codex-home", str(tmp_path / "codex"),
                      "--claude-home", str(tmp_path / "claude"), "--cursor-home", str(tmp_path / "cursor"),
                      "--cursor-user-dir", str(tmp_path / "user"), "--phone"])]
    assert "localhost:9001" in capsys.readouterr().out


def test_stop_and_status_use_shared_lifecycle(tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(server, "stop", lambda path: calls.append(path) or False)
    main(["stop", "--state-dir", str(tmp_path)])
    assert calls == [tmp_path]
    assert "No owned" in capsys.readouterr().out
    monkeypatch.setattr(server, "probe", lambda port: None)
    main(["status", "--port", "9001"])
    assert "not running" in capsys.readouterr().out


def test_background_start_preserves_relative_profile_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls = []
    monkeypatch.setattr(server, "start", lambda *args: calls.append(args) or {"pid": 123})
    main(["start", "--codex-home", "profiles/codex", "--claude-home", "profiles/claude",
          "--cursor-home", "profiles/cursor", "--cursor-user-dir", "profiles/user"])
    forwarded = calls[0][2]
    assert forwarded == ["--codex-home", str(tmp_path / "profiles/codex"),
                         "--claude-home", str(tmp_path / "profiles/claude"),
                         "--cursor-home", str(tmp_path / "profiles/cursor"),
                         "--cursor-user-dir", str(tmp_path / "profiles/user")]


def test_autostart_cli_is_opt_in_and_uninstall_removes_only_its_hook(tmp_path, monkeypatch, capsys):
    home = tmp_path / "codex"
    home.mkdir()
    original = {"description": "My hooks", "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "true"}]}]}}
    config = home / "hooks.json"
    config.write_text(json.dumps(original))
    main(["autostart", "enable", "--codex-home", str(home), "--state-dir", str(tmp_path / "state")])
    assert "SessionStart" in json.loads(config.read_text())["hooks"]
    main(["autostart", "status", "--codex-home", str(home)])
    assert "unverified" in capsys.readouterr().out
    monkeypatch.setattr("yourturn.cli.uninstall", lambda *args: None)
    main(["uninstall", "--harness", "codex", "--codex-home", str(home)])
    assert json.loads(config.read_text()) == original


def test_internal_managed_serve_rejects_missing_control_environment(monkeypatch, capsys):
    for name in ("YOUR_TURN_INSTANCE", "YOUR_TURN_STOP_TOKEN", "YOUR_TURN_STATE_DIR"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit) as error:
        main(["serve", "--managed"])
    assert error.value.code == 2
    assert "control environment" in capsys.readouterr().err


def test_module_entrypoint_preserves_command_exit_status(tmp_path):
    result = subprocess.run([sys.executable, "-m", "yourturn", "doctor", "--harness", "claude",
                             "--claude-home", str(tmp_path)], capture_output=True, text=True, cwd=tmp_path)
    assert result.returncode == 1
    assert "missing" in result.stdout


def test_cli_does_not_claim_modified_hook_was_disabled(tmp_path, capsys):
    main(["autostart", "enable", "--codex-home", str(tmp_path)])
    path = tmp_path / "hooks.json"
    config = json.loads(path.read_text())
    config["hooks"]["SessionStart"][0]["hooks"][0]["command"] += " && true"
    path.write_text(json.dumps(config))
    before = path.read_bytes()
    for action in ("enable", "disable"):
        with pytest.raises(SystemExit) as error:
            main(["autostart", action, "--codex-home", str(tmp_path)])
        assert error.value.code == 1
        assert "retained" in capsys.readouterr().err
        assert path.read_bytes() == before
    main(["autostart", "status", "--codex-home", str(tmp_path)])
    assert "modified" in capsys.readouterr().out
