"""`yourturn serve` runs the dashboard; `yourturn install` adds the Codex plugin first;
`yourturn mcp` is the plugin's MCP server."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
from pathlib import Path

MARKETPLACE_SOURCE = "martin-gomola/your-turn"
MARKETPLACE = "your-turn"
PLUGIN = f"your-turn@{MARKETPLACE}"


def install_plugin() -> bool:
    """Install the handoff skill and MCP server into Codex. Returns False when Codex is unavailable."""
    if not shutil.which("codex"):
        print("Codex CLI not found, so the plugin was not installed. The inbox still works, with weaker recaps.", flush=True)
        return False
    listed = subprocess.run(["codex", "plugin", "marketplace", "list"], capture_output=True, text=True)
    if not any(line.split()[:1] == [MARKETPLACE] for line in listed.stdout.splitlines()):
        subprocess.run(["codex", "plugin", "marketplace", "add", MARKETPLACE_SOURCE], check=True)
    subprocess.run(["codex", "plugin", "add", PLUGIN], check=True)
    print(f"Installed {PLUGIN}. Restart Codex so agents start writing Your Turn handoffs.", flush=True)
    return True


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="yourturn")
    commands = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("serve", "Run the dashboard on localhost"),
                            ("install", "Install the Codex plugin, then run the dashboard")):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("--port", type=int, default=8787)
        command.add_argument("--codex-home", type=Path,
                             default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")))
        command.add_argument("--claude-home", type=Path,
                             default=Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")))
        command.add_argument("--cursor-home", type=Path, default=Path.home() / ".cursor",
                             help="Cursor home holding projects/*/agent-transcripts (default: ~/.cursor)")
        command.add_argument("--cursor-user-dir", type=Path, default=None,
                             help="Cursor user data folder holding globalStorage/state.vscdb (default: per OS)")
    commands.add_parser("mcp", help="Run the stdio MCP server used by the Codex plugin")
    args = parser.parse_args(argv)

    if args.command == "install":
        try:
            install_plugin()
        except subprocess.CalledProcessError as error:
            parser.exit(1, f"Plugin install failed: {' '.join(error.cmd)}\n")

    if args.command == "mcp":
        from yourturn.mcp import serve as serve_mcp

        serve_mcp()
        return

    import uvicorn

    from yourturn.app import create_app

    from yourturn.config import load_history_days

    try:
        history_days = load_history_days()
    except (OSError, ValueError) as error:
        parser.error(f"Cannot read Your Turn config: {error}")

    print(f"Your Turn on http://127.0.0.1:{args.port}", flush=True)
    uvicorn.run(create_app(args.codex_home, history_days=history_days, claude_home=args.claude_home,
                           cursor_home=args.cursor_home, cursor_user_dir=args.cursor_user_dir), host="127.0.0.1", port=args.port, log_level="warning")
