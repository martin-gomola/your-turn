"""Opt-in Codex SessionStart hook; installed skill-only plugins stay free of hooks."""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shlex
import stat
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any

STATUS_MESSAGE = "Starting Your Turn inbox"
MATCHER = "*"


def _absolute(path: Path) -> Path:
    return Path(os.path.abspath(path.expanduser()))


def _safe(path: Path, *, directory: bool = False) -> os.stat_result | None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise ValueError(f"{path} must be a regular {'directory' if directory else 'file'}, not a symlink")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise ValueError(f"{path} is owned by another user")
    if info.st_mode & 0o022 or (not directory and info.st_nlink != 1):
        raise ValueError(f"{path} has unsafe permissions or hard links")
    return info


def _read(home: Path) -> tuple[dict[str, Any], bytes | None]:
    _safe(home, directory=True)
    path = home / "hooks.json"
    if _safe(path) is None:
        return {}, None
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(descriptor, "rb") as source:
        if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
            raise ValueError(f"{path} must be a regular file")
        raw = source.read()
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeError) as error:
        raise ValueError(f"Cannot parse {path}: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("hooks", {}), dict):
        raise ValueError(f"{path} must contain a JSON object with an object-valued hooks field")
    for event, groups in data.get("hooks", {}).items():
        if not isinstance(groups, list) or any(
            not isinstance(group, dict) or not isinstance(group.get("hooks", []), list)
            or any(not isinstance(handler, dict) for handler in group.get("hooks", []))
            for group in groups
        ):
            raise ValueError(f"{path}: hooks.{event} must contain matcher groups with hook objects")
    return data, raw


def _write(home: Path, data: dict[str, Any], previous: bytes | None) -> None:
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    _, current = _read(home)
    if current != previous:
        raise ValueError(f"{home / 'hooks.json'} changed during setup; try again")
    path = home / "hooks.json"
    if not data:
        path.unlink()
        return
    info = _safe(path)
    descriptor, temporary = tempfile.mkstemp(prefix=".your-turn-hooks-", dir=home)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as target:
            if info is not None:
                os.fchmod(target.fileno(), stat.S_IMODE(info.st_mode))
            json.dump(data, target, indent=2)
            target.write("\n")
            target.flush()
            os.fsync(target.fileno())
        _, current = _read(home)
        if current != previous:
            raise ValueError(f"{path} changed during setup; try again")
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _owned(handler: dict[str, Any]) -> list[str] | None:
    if handler.get("type") != "command" or handler.get("statusMessage") != STATUS_MESSAGE:
        return None
    command = handler.get("command")
    if not isinstance(command, str):
        return None
    try:
        args = shlex.split(command)
    except ValueError:
        return None
    if (len(args) != 11 or args[1:5] != ["-I", "-m", "yourturn.autostart", "run"]
            or args[5] != "--codex-home" or args[7] != "--state-dir"
            or args[9] != "--port"
            or not all(Path(args[index]).is_absolute() for index in (0, 6, 8))
            or command != shlex.join(args)):
        return None
    try:
        port = int(args[10])
    except ValueError:
        return None
    if str(port) != args[10] or not 1 <= port <= 65535:
        return None
    return args


def _without_owned(data: dict[str, Any]) -> bool:
    hooks = data.get("hooks", {})
    groups = hooks.get("SessionStart", [])
    kept = []
    removed = False
    for group in groups:
        handlers = [handler for handler in group.get("hooks", []) if _owned(handler) is None]
        if len(handlers) == len(group.get("hooks", [])):
            kept.append(group)
            continue
        removed = True
        if handlers or set(group) - {"matcher", "hooks"}:
            kept.append({**group, "hooks": handlers})
    if removed:
        if kept:
            hooks["SessionStart"] = kept
        else:
            hooks.pop("SessionStart", None)
        if not hooks:
            data.pop("hooks", None)
    return removed


def _modified(data: dict[str, Any]) -> bool:
    return any(handler.get("statusMessage") == STATUS_MESSAGE and _owned(handler) is None
               for group in data.get("hooks", {}).get("SessionStart", []) for handler in group.get("hooks", []))


def enable(codex_home: Path, state_dir: Path | None = None, port: int = 8787) -> str:
    if os.name == "nt":
        raise ValueError("Codex autostart is supported on macOS and Linux; use your-turn serve on Windows")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("port must be an integer between 1 and 65535")
    home = _absolute(codex_home)
    state = _absolute(state_dir if state_dir is not None else Path.home() / ".your-turn")
    executable = _absolute(Path(sys.executable))  # Keep a virtual environment's Python symlink.
    data, previous = _read(home)
    if _modified(data):
        raise ValueError(f"Autostart entry modified and retained; review {home / 'hooks.json'} before enabling")
    before = json.dumps(data, sort_keys=True)
    _without_owned(data)
    # Codex starts hooks in arbitrary project directories; exclude cwd and PYTHONPATH imports.
    args = [str(executable), "-I", "-m", "yourturn.autostart", "run", "--codex-home", str(home),
            "--state-dir", str(state), "--port", str(port)]
    data.setdefault("hooks", {}).setdefault("SessionStart", []).append({
        "matcher": MATCHER,
        "hooks": [{"type": "command", "command": shlex.join(args), "async": True,
                   "timeout": 10, "statusMessage": STATUS_MESSAGE}],
    })
    if json.dumps(data, sort_keys=True) != before:
        _write(home, data, previous)
    return "autostart enabled; Codex hook trust and loading remain unverified"


def disable(codex_home: Path) -> str:
    home = _absolute(codex_home)
    data, previous = _read(home)
    if _modified(data):
        raise ValueError(f"Autostart entry modified and retained; review {home / 'hooks.json'} before disabling")
    if _without_owned(data):
        _write(home, data, previous)
    return "autostart disabled"


def status(codex_home: Path) -> str:
    home = _absolute(codex_home)
    data, _ = _read(home)
    if _modified(data):
        return "autostart entry modified and retained; review hooks.json; Codex hook trust and loading remain unverified"
    groups = data.get("hooks", {}).get("SessionStart", [])
    owned = [(group, handler, args) for group in groups for handler in group.get("hooks", [])
             if (args := _owned(handler)) is not None]
    if not owned:
        return "autostart disabled"
    missing = [args[0] for _, _, args in owned if not Path(args[0]).is_file() or not os.access(args[0], os.X_OK)]
    runtime = (f"runtime missing or not executable: {', '.join(missing)}; re-enable from an installed runtime"
               if missing else "interpreter found; package availability unverified")
    if len(owned) != 1 or any(group.get("matcher") != MATCHER or handler.get("async") is not True
                              or handler.get("timeout") != 10 or args[6] != str(home) for group, handler, args in owned):
        runtime += "; hook settings changed, re-enable to refresh"
    return f"autostart enabled; {runtime}; Codex hook trust and loading remain unverified"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m yourturn.autostart")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--codex-home", type=Path, required=True)
    run.add_argument("--state-dir", type=Path, required=True)
    run.add_argument("--port", type=int, default=8787)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    state = _absolute(args.state_dir)
    try:
        _safe(state, directory=True)
        state.mkdir(mode=0o700, parents=True, exist_ok=True)
        log = state / "autostart.log"
        _safe(log)
        descriptor = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as output:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                try:
                    from yourturn.server import start

                    start(port=args.port, state_dir=state, serve_args=["--codex-home", str(_absolute(args.codex_home))])
                except (Exception, SystemExit):
                    traceback.print_exc(file=output)
    except (Exception, SystemExit) as error:
        print(f"Your Turn autostart could not write {state / 'autostart.log'}: {error}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
