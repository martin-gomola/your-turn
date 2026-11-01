"""`your-turn` (or `your-turn serve`) runs the dashboard; `your-turn install` sets up the handoff for every
agent app found (globally, never in a project) and exits; `your-turn uninstall` removes it; `your-turn
doctor` reports whether the installed handoff is current, without changing anything."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from yourturn.install import APPS, detect, doctor, install, uninstall

SERVE = "uvx --from git+https://github.com/martin-gomola/your-turn your-turn serve"


def main(argv: list[str] | None = None) -> int | None:
    argv = sys.argv[1:] if argv is None else argv
    # No subcommand, or only serve options: serve.
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv = ["serve", *argv]
    parser = argparse.ArgumentParser(prog="your-turn")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("serve", "Run the dashboard on localhost"),
                            ("install", "Set up the handoff for Codex, Claude Code and Cursor"),
                            ("uninstall", "Remove the handoff that install set up"),
                            ("doctor", "Check, without changing anything, whether the installed handoff is current")):
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

    if args.command in ("install", "uninstall", "doctor"):
        homes = {"codex": args.codex_home, "claude": args.claude_home, "cursor": args.cursor_home}
        harnesses = list(APPS) if args.harness == "all" else [args.harness] if args.harness else detect(homes)
        if args.command == "doctor":
            return doctor(harnesses, homes)
        try:
            (install if args.command == "install" else uninstall)(harnesses, homes)
        except subprocess.CalledProcessError as error:
            parser.exit(1, f"Plugin install failed: {' '.join(error.cmd)}\n")
        if args.command == "install":
            print(f"\n→ Start the inbox with: {SERVE}", flush=True)
        return

    import uvicorn

    from yourturn.app import create_app

    from yourturn.config import load_history_days

    try:
        history_days = load_history_days()
    except (OSError, ValueError) as error:
        parser.error(f"Cannot read Your Turn config: {error}")

    print(f"Starting Your Turn at http://127.0.0.1:{args.port}. Press Ctrl+C to stop it.", flush=True)
    try:
        uvicorn.run(create_app(args.codex_home, history_days=history_days, claude_home=args.claude_home,
                               cursor_home=args.cursor_home, cursor_user_dir=args.cursor_user_dir),
                    host="127.0.0.1", port=args.port, log_level="warning")
    except SystemExit as error:
        if error.code not in (None, 0):
            print(
                f"Could not start Your Turn. If it is already running, open http://127.0.0.1:{args.port} "
                f"in your browser. Otherwise, try another port: your-turn serve --port 8788.",
                file=sys.stderr,
            )
        raise
