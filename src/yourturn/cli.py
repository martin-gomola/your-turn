"""`yourturn serve` runs the dashboard; `yourturn install` sets up the handoff for every agent app
found (globally, never in a project) and exits; `yourturn uninstall` removes it."""

from __future__ import annotations

import argparse
import os
import subprocess
from pathlib import Path

from yourturn.install import APPS, detect, install, uninstall


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="yourturn")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("serve", "Run the dashboard on localhost"),
                            ("install", "Set up the handoff for Codex, Claude Code and Cursor"),
                            ("uninstall", "Remove the handoff that install set up")):
        command = commands.add_parser(name, help=help_text)
        if name == "serve":
            command.add_argument("--port", type=int, default=8787)
            command.add_argument("--cursor-user-dir", type=Path, default=None,
                                 help="Cursor user data folder holding globalStorage/state.vscdb (default: per OS)")
        else:
            command.add_argument("--harness", choices=[*APPS, "all"], default=None,
                                 help="Only this app, or all three (default: every app whose folder exists)")
        command.add_argument("--codex-home", type=Path,
                             default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")))
        command.add_argument("--claude-home", type=Path,
                             default=Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")))
        command.add_argument("--cursor-home", type=Path, default=Path.home() / ".cursor",
                             help="Cursor home holding projects/*/agent-transcripts (default: ~/.cursor)")
    args = parser.parse_args(argv)

    if args.command in ("install", "uninstall"):
        homes = {"codex": args.codex_home, "claude": args.claude_home, "cursor": args.cursor_home}
        harnesses = list(APPS) if args.harness == "all" else [args.harness] if args.harness else detect(homes)
        try:
            (install if args.command == "install" else uninstall)(harnesses, homes)
        except subprocess.CalledProcessError as error:
            parser.exit(1, f"Plugin install failed: {' '.join(error.cmd)}\n")
        if args.command == "install":
            print("\n→ Start the inbox with: your-turn serve", flush=True)
        return

    import uvicorn

    from yourturn.app import create_app

    from yourturn.config import load_history_days

    try:
        history_days = load_history_days()
    except (OSError, ValueError) as error:
        parser.error(f"Cannot read Your Turn config: {error}")

    print(f"Your Turn on http://127.0.0.1:{args.port}. It runs in this terminal until you press Ctrl+C.", flush=True)
    uvicorn.run(create_app(args.codex_home, history_days=history_days, claude_home=args.claude_home,
                           cursor_home=args.cursor_home, cursor_user_dir=args.cursor_user_dir), host="127.0.0.1", port=args.port, log_level="warning")
