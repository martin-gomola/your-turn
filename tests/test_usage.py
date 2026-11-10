import json
import subprocess
import sys
from pathlib import Path

import pytest

from yourturn import usage


@pytest.fixture
def paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every Your Turn file at a temporary folder; returns a Claude home with an existing status line."""
    ours = tmp_path / "your-turn"
    for name, file in (("CAPTURE_PATH", "claude-usage.json"), ("SCRIPT_PATH", "claude-statusline.py"),
                       ("PREVIOUS_PATH", "claude-statusline-previous.json")):
        monkeypatch.setattr(usage, name, ours / file)
    home = tmp_path / "claude"
    home.mkdir()
    (home / "settings.json").write_text(json.dumps({"model": "opus", "statusLine": {
        "type": "command", "command": "echo mine", "padding": 1}}))
    return home


def test_windows_convert_claude_limits_to_codex_shape() -> None:
    limits = {"five_hour": {"used_percentage": 18.4, "resets_at": 1_800_000_000}, "seven_day": {"used_percentage": 151},
              "other": {"used_percentage": 3}}
    assert usage.windows(limits) == [
        {"used_percent": 18.4, "window_minutes": 300, "resets_at": "2027-01-15T08:00:00Z"},
        {"used_percent": 100.0, "window_minutes": 10_080, "resets_at": ""},
    ]
    assert usage.windows(None) == [] and usage.windows({"five_hour": {"used_percentage": "18"}}) == []


def test_install_chains_previous_status_line_and_script_captures(paths: Path) -> None:
    assert "echo mine" in usage.install(paths)
    settings = json.loads((paths / "settings.json").read_text())
    assert settings["model"] == "opus" and settings["statusLine"] == {"type": "command", "command": usage.command(), "padding": 1}
    assert usage.state(paths) == "current"
    status = {"rate_limits": {"five_hour": {"used_percentage": 42, "resets_at": 1_800_000_000}}}
    shown = subprocess.run([sys.executable, str(usage.SCRIPT_PATH)], input=json.dumps(status), capture_output=True, text=True)
    assert shown.stdout == "mine\n"  # The user's own status line still prints.
    windows, captured_at = usage.read(usage.CAPTURE_PATH)
    assert windows[0]["used_percent"] == 42 and captured_at
    # Installing again keeps the original chained command instead of chaining the script to itself.
    usage.install(paths)
    assert "echo mine" in usage.SCRIPT_PATH.read_text()


def test_uninstall_restores_the_previous_status_line_exactly(paths: Path) -> None:
    before = json.loads((paths / "settings.json").read_text())
    usage.install(paths)
    assert "restored" in usage.uninstall(paths)
    assert json.loads((paths / "settings.json").read_text()) == before
    assert not usage.SCRIPT_PATH.exists() and usage.state(paths) == "off"


def test_install_without_previous_status_line_removes_it_again(paths: Path) -> None:
    (paths / "settings.json").write_text("{}")
    usage.install(paths)
    shown = subprocess.run([sys.executable, str(usage.SCRIPT_PATH)], input="not json", capture_output=True, text=True)
    assert shown.returncode == 0 and shown.stdout == ""  # A bad payload never breaks the status line.
    usage.uninstall(paths)
    assert json.loads((paths / "settings.json").read_text()) == {}


def test_unparsable_settings_are_never_overwritten(paths: Path) -> None:
    (paths / "settings.json").write_text("{ // comment\n}")
    with pytest.raises(ValueError):
        usage.install(paths)
    assert (paths / "settings.json").read_text() == "{ // comment\n}"
    assert usage.state(paths) == "unreadable"

