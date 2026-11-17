from pathlib import Path

import pytest

from yourturn.config import CONFIG_PATH, DEFAULT_HISTORY_DAYS, load_history_days, load_launcher


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


def test_launcher_defaults_to_the_four_built_in_tiles(tmp_path: Path) -> None:
    slots = load_launcher(tmp_path / "launcher.toml")
    assert len(slots) == 16
    assert [(s.label, s.app, s.icon) for s in slots[:3]] == [
        ("Codex", "Codex", "codex"), ("Claude Code", "Claude", "claude"), ("Cursor", "Cursor", "cursor")]
    assert slots[3].settings and all(slot is None for slot in slots[4:])


def test_launcher_file_defines_apps_commands_and_empty_slots(tmp_path: Path) -> None:
    path = tmp_path / "launcher.toml"
    path.write_text(f"""
[[shortcut]]
slot = 2
label = "Ghostty"
app = "Ghostty"

[[shortcut]]
slot = 9
label = "Restart inbox"
command = ["make", "restart"]
cwd = "{tmp_path}"
icon = "tool"
""")
    slots = load_launcher(path)
    assert slots[0] is None and slots[2] is None
    assert (slots[1].key, slots[1].app, slots[1].icon) == ("slot-2", "Ghostty", "app")
    assert (slots[8].command, slots[8].cwd, slots[8].icon) == (("make", "restart"), str(tmp_path), "tool")


def test_example_launcher_file_loads() -> None:
    slots = load_launcher(Path(__file__).resolve().parents[1] / "launcher.toml.example")
    assert [slot.label for slot in slots[:5]] == ["Codex", "Claude Code", "Cursor", "Your Turn Settings", "Ghostty"]


@pytest.mark.parametrize("entry", [
    'slot = 17\nlabel = "X"\napp = "Ghostty"',
    'slot = 1\nlabel = "X"',
    'slot = 1\nlabel = "X"\napp = "Ghostty"\ncommand = ["ls"]',
    'slot = 1\nlabel = "X"\napp = "/Applications/Ghostty.app"',
    'slot = 1\nlabel = "X"\napp = "https://example.com"',
    'slot = 1\nlabel = "X"\napp = "$(touch /tmp/unsafe)"',
    'slot = 1\nlabel = "X"\ncommand = "make up"',
    'slot = 1\nlabel = "X"\ncommand = []',
    'slot = 1\nlabel = "X"\ncommand = ["make", ""]',
    'slot = 1\nlabel = "X"\ncommand = ["ls"]\ncwd = "relative/dir"',
    'slot = 1\nlabel = "X"\ncommand = ["ls"]\ncwd = "/no/such/folder"',
    'slot = 1\nlabel = "X"\napp = "Ghostty"\ncwd = "/tmp"',
    'slot = 1\nlabel = "X"\nsettings = false',
    'slot = 1\nlabel = ""\napp = "Ghostty"',
    'slot = 1\nlabel = "X"\napp = "Ghostty"\nicon = "rocket"',
    'slot = 1\nlabel = "X"\napp = "Ghostty"\nshell = true',
])
def test_launcher_rejects_invalid_entries(tmp_path: Path, entry: str) -> None:
    path = tmp_path / "launcher.toml"
    path.write_text("[[shortcut]]\n" + entry + "\n")
    with pytest.raises(ValueError):
        load_launcher(path)


def test_launcher_rejects_duplicate_slots_and_stray_keys(tmp_path: Path) -> None:
    path = tmp_path / "launcher.toml"
    path.write_text('[[shortcut]]\nslot = 1\nlabel = "A"\napp = "A"\n[[shortcut]]\nslot = 1\nlabel = "B"\napp = "B"\n')
    with pytest.raises(ValueError, match="used twice"):
        load_launcher(path)
    path.write_text('history_days = 3\n')
    with pytest.raises(ValueError):
        load_launcher(path)
