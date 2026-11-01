"""`your-turn` (or `your-turn serve`) runs the dashboard; `your-turn install` sets up the handoff for every
agent app found (globally, never in a project), then, run in a terminal, starts the dashboard unless it is
already running; `your-turn uninstall` removes it; `your-turn
doctor` reports whether the installed handoff is current, without changing anything; `your-turn cursor-rule`
prints the Cursor User Rule to paste into Cursor's settings."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

from yourturn.install import APPS, detect, doctor, install, rule_text, uninstall

SERVE = "uvx --from git+https://github.com/martin-gomola/your-turn your-turn serve"
PORT = 8787


def _url(port: int) -> str:
    """The address to show: the server binds only 127.0.0.1, which `localhost` reaches and is easier to type."""
    return f"http://localhost:{port}"


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _inbox_running(port: int) -> bool:
    """Whether Your Turn already answers on the port, as `make up` checks it."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/inbox", timeout=1):
            return True
    except OSError:
        return False


def main(argv: list[str] | None = None) -> int | None:
    argv = sys.argv[1:] if argv is None else argv
    # No subcommand, or only serve options: serve.
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help")):
        argv = ["serve", *argv]
    parser = argparse.ArgumentParser(prog="your-turn")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("serve", "Run the dashboard on localhost"),
                            ("install", "Set up the handoff for Codex, Claude Code and Cursor, then start the dashboard"),
                            ("uninstall", "Remove the handoff that install set up"),
                            ("doctor", "Check, without changing anything, whether the installed handoff is current")):
        command = commands.add_parser(name, help=help_text)
        if name == "serve":
            command.add_argument("--port", type=int, default=PORT)
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
    commands.add_parser("cursor-rule", help="Print the Cursor User Rule to paste into Customize → Rules")
    args = parser.parse_args(argv)

    if args.command == "cursor-rule":
        print(rule_text("cursor"), end="", flush=True)
        return 0

    if args.command in ("install", "uninstall", "doctor"):
        homes = {"codex": args.codex_home, "claude": args.claude_home, "cursor": args.cursor_home}
        harnesses = list(APPS) if args.harness == "all" else [args.harness] if args.harness else detect(homes)
        if args.command == "doctor":
            return doctor(harnesses, homes)
        try:
            done = (install if args.command == "install" else uninstall)(harnesses, homes)
        except subprocess.CalledProcessError as error:
            parser.exit(1, f"Plugin install failed: {' '.join(error.cmd)}\n")
        if args.command == "uninstall":
            return
        names = [APPS[harness] for harness in done]
        apps = ", ".join(names[:-1]) + f" and {names[-1]}" if len(names) > 1 else "".join(names)
        restart = f"Restart {apps} to load the handoff" if names else ""
        # Run from a script, or with input or output redirected, install only sets up and exits.
        if not _interactive():
            print(f"\n→ {restart}, then start the inbox with: {SERVE}" if restart else f"\n→ Start the inbox with: {SERVE}",
                  flush=True)
            return
        if restart:
            print(f"\n→ {restart}.", flush=True)
        if _inbox_running(PORT):
            print(f"→ Your Turn is already running at {_url(PORT)}", flush=True)
            return
        print(f"→ Next time, start the inbox with: {SERVE}", flush=True)
        args.port, args.cursor_user_dir = PORT, None

    import uvicorn

    from yourturn.app import create_app

    from yourturn.config import load_history_days

    try:
        history_days = load_history_days()
    except (OSError, ValueError) as error:
        parser.error(f"Cannot read Your Turn config: {error}")

    print(f"Starting Your Turn at {_url(args.port)}. Press Ctrl+C to stop it.", flush=True)
    try:
        uvicorn.run(create_app(args.codex_home, history_days=history_days, claude_home=args.claude_home,
                               cursor_home=args.cursor_home, cursor_user_dir=args.cursor_user_dir),
                    host="127.0.0.1", port=args.port, log_level="warning")
    except SystemExit as error:
        if error.code not in (None, 0):
            print(
                f"Could not start Your Turn. If it is already running, open {_url(args.port)} "
                f"in your browser. Otherwise, try another port: your-turn serve --port 8788.",
                file=sys.stderr,
            )
        raise
