"""Local dashboard configuration, loaded when the server starts."""

import os
from pathlib import Path
import re
import shlex
import tomllib

DEFAULT_HISTORY_DAYS = 14
CONFIG_PATH = Path(__file__).resolve().parents[2] / "config.toml"


def load_launcher_apps(path: Path) -> dict[str, str]:
    """Extra named macOS apps in slots 5–16; file values never become shell commands."""
    values = {}
    if path.exists():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            key, separator, value = line.partition("=")
            key = key.strip()
            if not separator or not re.fullmatch(r"YOUR_TURN_LAUNCHER_(?:[5-9]|1[0-6])", key):
                raise ValueError(f"{path}:{number}: expected YOUR_TURN_LAUNCHER_5 through _16")
            parts = shlex.split(value, comments=True)
            if len(parts) > 1:
                raise ValueError(f"{path}:{number}: quote app names containing spaces")
            values[key] = parts[0] if parts else ""
    apps = {"codex": "Codex", "claude": "Claude", "cursor": "Cursor"}
    for slot in range(5, 17):
        key = f"YOUR_TURN_LAUNCHER_{slot}"
        name = os.environ.get(key, values.get(key, "")).strip()
        if not name:
            continue
        if not re.fullmatch(r"[\w][\w .+&()'-]{0,79}", name):
            raise ValueError(f"{key}: expected an installed app name, not a command, path or URL")
        apps[f"slot-{slot}"] = name
    return apps


def load_history_days(path: Path = CONFIG_PATH) -> int:
    if not path.exists():
        return DEFAULT_HISTORY_DAYS
    with path.open("rb") as handle:
        days = tomllib.load(handle).get("history_days", DEFAULT_HISTORY_DAYS)
    if type(days) is not int or days < 1:
        raise ValueError("history_days must be a positive integer")
    return days
