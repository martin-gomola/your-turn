"""`your-turn` (or `your-turn serve`) runs the dashboard; `your-turn install` sets up the handoff for every
agent app found (globally, never in a project), then, run in a terminal, starts the dashboard unless it is
already running; `your-turn uninstall` removes it; `your-turn
doctor` reports whether the installed handoff is current, without changing anything; `your-turn cursor-rule`
prints the Cursor User Rule to paste into Cursor's settings."""

from __future__ import annotations

import argparse
import ipaddress
import os
import re
import secrets
import subprocess
import sys
import urllib.request
from pathlib import Path

from yourturn.install import APPS, detect, doctor, install, rule_text, uninstall

SERVE = "uvx your-turn@latest serve"
PORT = 8787


def _url(port: int) -> str:
    """The address to show: the server binds only 127.0.0.1, which `localhost` reaches and is easier to type."""
    return f"http://localhost:{port}"


TOKEN_PATH = Path.home() / ".your-turn" / "phone-token"
HOTSPOT = ipaddress.ip_network("172.20.10.0/28")  # iPhone Personal Hotspot, also over USB


TAILNET = ipaddress.ip_network("100.64.0.0/10")
TAILSCALE = ("tailscale", "/Applications/Tailscale.app/Contents/MacOS/Tailscale")


def _tailscale_address() -> list[str]:
    """This Mac's Tailscale IPv4, asked of Tailscale itself: other VPNs (Twingate) use 100.64/10 too."""
    for binary in TAILSCALE:
        try:
            out = subprocess.run([binary, "ip", "-4"], capture_output=True, text=True, timeout=5).stdout.split()
        except (OSError, subprocess.SubprocessError):
            continue
        if out and re.fullmatch(r"\d+\.\d+\.\d+\.\d+", out[0]) and ipaddress.ip_address(out[0]) in TAILNET:
            return [out[0]]
    return []


def _lan_addresses() -> list[str]:
    """Private IPv4 addresses of this Mac, the iPhone hotspot (USB cable) first; skips VPN (100.64/10) and link-local."""
    try:
        out = subprocess.run(["ifconfig"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    found = {ipaddress.ip_address(a) for a in re.findall(r"inet (\d+\.\d+\.\d+\.\d+)", out)}
    lan = [a for a in found if a.is_private and not a.is_loopback and not a.is_link_local]
    return [str(a) for a in sorted(lan, key=lambda a: (a not in HOTSPOT, a))]


def _phone_token() -> str:
    """One token kept across restarts, so the phone's home-screen icon keeps working."""
    try:
        return TOKEN_PATH.read_text().strip()
    except FileNotFoundError:
        token = secrets.token_urlsafe(24)
        TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_PATH.touch(mode=0o600)
        TOKEN_PATH.write_text(token)
        return token


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
            command.add_argument("--phone", action="store_true",
                                 help="Also serve on this Mac's Wi-Fi or USB-hotspot address, behind a token in a QR code")
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
            start = f"start the inbox with: {SERVE} (or `make up` in a clone)"
            print(f"\n→ {restart}, then {start}" if restart else f"\n→ {start[0].upper()}{start[1:]}", flush=True)
            return
        if restart:
            print(f"\n→ {restart}.", flush=True)
        if _inbox_running(PORT):
            print(f"→ Your Turn is already running at {_url(PORT)}", flush=True)
            return
        print(f"→ Next time, start the inbox with: {SERVE}", flush=True)
        args.port, args.cursor_user_dir, args.phone = PORT, None, False

    import uvicorn

    from yourturn.app import create_app

    from yourturn.config import load_history_days

    try:
        history_days = load_history_days()
    except (OSError, ValueError) as error:
        parser.error(f"Cannot read Your Turn config: {error}")

    host, token, lan = "127.0.0.1", None, ()
    if args.phone:
        # Tailscale first: it reaches the phone on any network, office Wi-Fi isolation included.
        lan = tuple(_tailscale_address() + _lan_addresses())
        if not lan:
            parser.error("No Tailscale, Wi-Fi or USB-hotspot address found. Connect Tailscale, join a network, "
                         "or turn on Personal Hotspot on the iPhone and connect it by cable.")
        import segno

        host, token = "0.0.0.0", _phone_token()
        phone_url = f"http://{lan[0]}:{args.port}/?t={token}"
        segno.make(phone_url, error="l").terminal(compact=True)
        print(f"Scan with the iPhone camera, then Share → Add to Home Screen: {phone_url}", flush=True)
        if len(lan) > 1:
            print(f"Other addresses of this Mac: {', '.join(lan[1:])}", flush=True)
        if ipaddress.ip_address(lan[0]) in TAILNET:
            print("This is the Tailscale address: the iPhone needs the Tailscale app, signed in to the same account.",
                  flush=True)
        elif ipaddress.ip_address(lan[0]) not in HOTSPOT:
            print("This is the Wi-Fi address: the iPhone must be on the same Wi-Fi. Over the USB cable instead, "
                  "turn on Personal Hotspot on the iPhone, then run this again.", flush=True)
    print(f"Starting Your Turn at {_url(args.port)}. Press Ctrl+C to stop it.", flush=True)
    try:
        uvicorn.run(create_app(args.codex_home, history_days=history_days, claude_home=args.claude_home,
                               cursor_home=args.cursor_home, cursor_user_dir=args.cursor_user_dir,
                               phone_token=token, lan_hosts=lan),
                    host=host, port=args.port, log_level="warning")
    except SystemExit as error:
        if error.code not in (None, 0):
            print(
                f"Could not start Your Turn. If it is already running, open {_url(args.port)} "
                f"in your browser. Otherwise, try another port: your-turn serve --port 8788.",
                file=sys.stderr,
            )
        raise
