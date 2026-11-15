from pathlib import Path

import pytest

from yourturn.config import CONFIG_PATH, DEFAULT_HISTORY_DAYS, load_history_days, load_launcher_apps


def test_default_and_configured_history(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    assert load_history_days(path) == DEFAULT_HISTORY_DAYS
    path.write_text("history_days = 7\n")
    assert load_history_days(path) == 7


@pytest.mark.parametrize("value", ["0", "-1", "true", '"seven"', "1.5", "["])
def test_rejects_invalid_history(tmp_path: Path, value: str) -> None:
    path = tmp_path / "config.toml"
    path.write_text(f"history_days = {value}\n")
    with pytest.raises(ValueError):
        load_history_days(path)


def test_checkout_config_does_not_depend_on_working_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    assert CONFIG_PATH == Path(__file__).resolve().parents[1] / "config.toml"
    assert load_history_days() > 0


def test_launcher_slots_default_to_empty_and_env_overrides_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "launcher.env"
    assert load_launcher_apps(path) == {"codex": "Codex", "claude": "Claude", "cursor": "Cursor"}
    path.write_text('# Local apps\nYOUR_TURN_LAUNCHER_5=Ghostty\nYOUR_TURN_LAUNCHER_9="Activity Monitor" # tools\nYOUR_TURN_LAUNCHER_16=\n')
    assert load_launcher_apps(path)["slot-5"] == "Ghostty"
    assert load_launcher_apps(path)["slot-9"] == "Activity Monitor"
    assert "slot-16" not in load_launcher_apps(path)
    monkeypatch.setenv("YOUR_TURN_LAUNCHER_5", "Terminal")
    assert load_launcher_apps(path)["slot-5"] == "Terminal"
    monkeypatch.setenv("YOUR_TURN_LAUNCHER_5", "")
    assert "slot-5" not in load_launcher_apps(path)


@pytest.mark.parametrize("line", [
    'YOUR_TURN_LAUNCHER_4=Ghostty', 'YOUR_TURN_LAUNCHER_17=Ghostty',
    'YOUR_TURN_LAUNCHER_5="/Applications/Ghostty.app"', 'YOUR_TURN_LAUNCHER_5="https://example.com"',
    'YOUR_TURN_LAUNCHER_5="$(touch /tmp/unsafe)"', 'YOUR_TURN_LAUNCHER_5=Activity Monitor',
    'YOUR_TURN_LAUNCHER_5="unclosed', 'not an assignment', 'YOUR_TURN_LAUNCHER_5="-a Ghostty"',
])
def test_launcher_rejects_invalid_slots_commands_and_paths(tmp_path: Path, line: str) -> None:
    path = tmp_path / "launcher.env"
    path.write_text(line)
    with pytest.raises(ValueError):
        load_launcher_apps(path)
