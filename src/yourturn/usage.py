"""Claude Code plan usage (5-hour and weekly windows) for the Deck, captured from the status line.

Claude Code writes no quota to its transcripts. The one documented source is the JSON it pipes to a
status line command: `rate_limits.five_hour` and `rate_limits.seven_day`, each with `used_percentage`
and `resets_at` (epoch seconds), present for Pro, Max and Ultra plans after a session's first reply
(https://code.claude.com/docs/en/statusline.md).

`install --claude-usage` points Claude Code's `statusLine` at a small stdlib-only script that saves
those windows to CAPTURE_PATH and then runs the status line command that was there before, so the
user's own status line is unchanged. No model is called: it is a local command Claude Code already
runs. `uninstall --claude-usage` restores the previous `statusLine` exactly.
"""

from __future__ import annotations

import json
import os
import shlex
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

HOME = Path.home() / ".your-turn"
CAPTURE_PATH = HOME / "claude-usage.json"
SCRIPT_PATH = HOME / "claude-statusline.py"
PREVIOUS_PATH = HOME / "claude-statusline-previous.json"
WINDOWS = {"five_hour": 300, "seven_day": 10_080}

# The installed script. It must stay fast and dependency-free: Claude Code runs it on every refresh.
SCRIPT = '''#!/usr/bin/env python3
"""Written by `your-turn install --claude-usage`. Saves Claude Code's plan usage for the Your Turn Deck,
then runs the status line command that was configured before, so the status line looks the same."""
import json, os, subprocess, sys, tempfile, time
CAPTURE, PREVIOUS = {capture!r}, {previous!r}
raw = sys.stdin.read()
try:
    limits = json.loads(raw).get("rate_limits")
    if isinstance(limits, dict) and limits:
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(CAPTURE))
        with os.fdopen(fd, "w") as out:
            json.dump({{"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "rate_limits": limits}}, out)
        os.replace(tmp, CAPTURE)
except Exception:
    pass  # Never break the status line over a capture problem.
if PREVIOUS:
    shown = subprocess.run(PREVIOUS, shell=True, input=raw, capture_output=True, text=True)
    sys.stdout.write(shown.stdout)
'''


def windows(limits: object) -> list[dict[str, Any]]:
    """Claude's `rate_limits` as the Codex-shaped windows the Deck already reads."""
    if not isinstance(limits, dict):
        return []
    out = []
    for name, minutes in WINDOWS.items():
        raw = limits.get(name)
        if not isinstance(raw, dict):
            continue
        used, resets = raw.get("used_percentage"), raw.get("resets_at")
        if type(used) not in (int, float):
            continue
        out.append({
            "used_percent": max(0.0, min(100.0, float(used))),
            "window_minutes": minutes,
            "resets_at": datetime.fromtimestamp(resets, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if type(resets) in (int, float) and resets > 0 else "",
        })
    return out


_cache: dict[str, Any] = {"key": None, "value": ([], "")}


def read(path: Path | None = None) -> tuple[list[dict[str, Any]], str]:
    """(windows, captured_at) from the capture file; ([], "") when absent or unreadable. Cached by mtime."""
    path = path or CAPTURE_PATH
    try:
        key = (str(path), path.stat().st_mtime_ns)
    except OSError:
        return [], ""
    if _cache["key"] != key:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            value = (windows(data.get("rate_limits")), str(data.get("at") or ""))
        except (OSError, ValueError, AttributeError):
            value = ([], "")
        _cache.update(key=key, value=value)
    return _cache["value"]


# --- Opt-in setup ---------------------------------------------------------------------------------

def _settings(home: Path) -> tuple[Path, dict[str, Any]]:
    path = home / "settings.json"
    if not path.is_file():
        return path, {}
    data = json.loads(path.read_text(encoding="utf-8"))  # A parse error stops setup: never overwrite it.
    if not isinstance(data, dict):
        raise ValueError(f"{path} is not a JSON object")
    return path, data


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def command() -> str:
    """The `statusLine.command` install sets: plain python3, so each refresh starts in milliseconds."""
    return f"python3 {shlex.quote(str(SCRIPT_PATH))}"


def state(home: Path) -> str:
    """'current', 'off', 'content mismatch' (script outdated) or 'unreadable', for `doctor`."""
    try:
        _, data = _settings(home)
    except (OSError, ValueError):
        return "unreadable"
    line = data.get("statusLine")
    if not (isinstance(line, dict) and line.get("command") == command()):
        return "off"
    try:
        previous = json.loads(PREVIOUS_PATH.read_text(encoding="utf-8"))
        expected = _script(previous.get("command") if isinstance(previous, dict) else None)
        return "current" if SCRIPT_PATH.read_text(encoding="utf-8") == expected else "content mismatch"
    except (OSError, ValueError):
        return "content mismatch"


def _script(previous: str | None) -> str:
    return SCRIPT.format(capture=str(CAPTURE_PATH), previous=previous or "")


def install(home: Path) -> str:
    """Route Claude Code's status line through the capture script, keeping the previous one chained."""
    path, data = _settings(home)
    line = data.get("statusLine")
    ours = isinstance(line, dict) and line.get("command") == command()
    if not ours:
        _write_json(PREVIOUS_PATH, line if isinstance(line, dict) else None)
    saved = json.loads(PREVIOUS_PATH.read_text(encoding="utf-8")) if PREVIOUS_PATH.is_file() else None
    chained = saved.get("command") if isinstance(saved, dict) and saved.get("type", "command") == "command" else None
    SCRIPT_PATH.parent.mkdir(parents=True, exist_ok=True)
    SCRIPT_PATH.write_text(_script(chained), encoding="utf-8")
    SCRIPT_PATH.chmod(0o755)
    data["statusLine"] = {**(saved if isinstance(saved, dict) else {}), "type": "command", "command": command()}
    _write_json(path, data)
    return f"plan usage capture on (status line chains {chained!r})" if chained else "plan usage capture on"


def uninstall(home: Path) -> str:
    """Restore the status line that was there before `install`, then remove the script and capture."""
    path, data = _settings(home)
    line = data.get("statusLine")
    if not (isinstance(line, dict) and line.get("command") == command()):
        return "plan usage capture not on"
    saved = json.loads(PREVIOUS_PATH.read_text(encoding="utf-8")) if PREVIOUS_PATH.is_file() else None
    if isinstance(saved, dict):
        data["statusLine"] = saved
    else:
        data.pop("statusLine", None)
    _write_json(path, data)
    for leftover in (SCRIPT_PATH, PREVIOUS_PATH, CAPTURE_PATH):
        leftover.unlink(missing_ok=True)
    return "plan usage capture off, previous status line restored"
