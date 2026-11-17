"""Local dashboard configuration, loaded when the server starts."""

from dataclasses import dataclass
from pathlib import Path
import re
import tomllib

DEFAULT_HISTORY_DAYS = 14
CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.toml"

LAUNCHER_SLOTS = 16
# Icon names a shortcut may pick, mapped to the page's SVG symbols.
LAUNCHER_ICONS = {"codex": "i-harness-codex", "claude": "i-harness-claude", "cursor": "i-harness-cursor",
                  "settings": "i-settings", "command": "i-command", "app": "i-external", "tool": "i-tool",
                  "workspace": "i-workspace", "inbox": "i-inbox"}
APP_NAME = re.compile(r"[\w][\w .+&()'-]{0,79}")
# Without a launcher.toml the Deck keeps its four built-in tiles.
DEFAULT_LAUNCHER = """
[[shortcut]]
slot = 1
label = "Codex"
app = "Codex"
icon = "codex"

[[shortcut]]
slot = 2
label = "Claude Code"
app = "Claude"
icon = "claude"

[[shortcut]]
slot = 3
label = "Cursor"
app = "Cursor"
icon = "cursor"

[[shortcut]]
slot = 4
label = "Your Turn Settings"
settings = true
"""


@dataclass(frozen=True)
class Shortcut:
    """One launcher tile. Only `key` reaches the browser; the server resolves it back to this entry."""

    slot: int
    label: str
    icon: str
    app: str = ""
    command: tuple[str, ...] = ()
    cwd: str = ""
    settings: bool = False

    @property
    def key(self) -> str:
        return f"slot-{self.slot}"


def load_launcher(path: Path) -> list[Shortcut | None]:
    """All 16 launcher slots from `launcher.toml` (the built-in four when it is missing); `None` is an empty slot.

    Each `[[shortcut]]` names its `slot` and `label` and exactly one action: `app` (an installed macOS app name),
    `command` (an argument list, optionally with `cwd`, opened in a new Terminal window; never a shell string), or
    `settings = true`. Anything else is an error at start-up, so a typo never silently drops a tile.
    """
    text = path.read_text(encoding="utf-8") if path.exists() else DEFAULT_LAUNCHER
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ValueError(f"{path}: {error}") from None
    if set(data) - {"shortcut"} or not isinstance(data.get("shortcut", []), list):
        raise ValueError(f"{path}: expected only [[shortcut]] entries")
    slots: list[Shortcut | None] = [None] * LAUNCHER_SLOTS
    for number, entry in enumerate(data.get("shortcut", []), 1):
        where = f"{path}: shortcut {number}"
        if not isinstance(entry, dict) or set(entry) - {"slot", "label", "icon", "app", "command", "cwd", "settings"}:
            raise ValueError(f"{where}: unknown key; use slot, label, icon and one of app, command or settings")
        slot = entry.get("slot")
        if type(slot) is not int or not 1 <= slot <= LAUNCHER_SLOTS:
            raise ValueError(f"{where}: slot must be a number from 1 to {LAUNCHER_SLOTS}")
        if slots[slot - 1] is not None:
            raise ValueError(f"{where}: slot {slot} is used twice")
        label = entry.get("label")
        if not isinstance(label, str) or not 0 < len(label.strip()) <= 40 or any(c in label for c in "\r\n\t"):
            raise ValueError(f"{where}: label must be 1 to 40 characters on one line")
        actions = [name for name in ("app", "command", "settings") if name in entry]
        if len(actions) != 1:
            raise ValueError(f"{where}: give exactly one of app, command or settings")
        action = actions[0]
        icon = entry.get("icon", {"app": "app", "command": "command", "settings": "settings"}[action])
        if icon not in LAUNCHER_ICONS:
            raise ValueError(f"{where}: icon must be one of {', '.join(sorted(LAUNCHER_ICONS))}")
        if "cwd" in entry and action != "command":
            raise ValueError(f"{where}: cwd applies only to a command")
        shortcut = Shortcut(slot, label.strip(), icon)
        if action == "app":
            app = entry["app"]
            if not isinstance(app, str) or not APP_NAME.fullmatch(app):
                raise ValueError(f"{where}: app must be an installed app name, not a command, path or URL")
            shortcut = Shortcut(slot, label.strip(), icon, app=app)
        elif action == "settings":
            if entry["settings"] is not True:
                raise ValueError(f"{where}: settings must be true")
            shortcut = Shortcut(slot, label.strip(), icon, settings=True)
        else:
            command = entry["command"]
            if (not isinstance(command, list) or not command
                    or not all(isinstance(part, str) and part and "\0" not in part for part in command)):
                raise ValueError(f'{where}: command must be a list of arguments, such as ["make", "up"]')
            cwd = ""
            if "cwd" in entry:
                if not isinstance(entry["cwd"], str):
                    raise ValueError(f"{where}: cwd must be a folder path")
                folder = Path(entry["cwd"]).expanduser()
                if not folder.is_absolute() or not folder.is_dir():
                    raise ValueError(f"{where}: cwd must be an existing folder (absolute or ~/)")
                cwd = str(folder)
            shortcut = Shortcut(slot, label.strip(), icon, command=tuple(command), cwd=cwd)
        slots[slot - 1] = shortcut
    return slots


def load_history_days(path: Path = CONFIG_PATH) -> int:
    if not path.exists():
        return DEFAULT_HISTORY_DAYS
    with path.open("rb") as handle:
        days = tomllib.load(handle).get("history_days", DEFAULT_HISTORY_DAYS)
    if type(days) is not int or days < 1:
        raise ValueError("history_days must be a positive integer")
    return days
