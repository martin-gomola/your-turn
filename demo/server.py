"""Disposable agent homes and a throwaway Your Turn server, so a demo never reads or writes a real chat or preference."""

from __future__ import annotations

import json
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path

from demo.chats import demo_other_chats
from demo.fixtures import Chat, ClaudeChat, CursorChat

ROOT = Path(__file__).resolve().parent.parent


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def wait_for(url: str, server: subprocess.Popen) -> None:
    for _ in range(40):
        if server.poll() is not None:
            sys.exit("Your Turn server exited before it was ready")
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except OSError:
            time.sleep(0.25)
    sys.exit(f"Server did not start on {url}")


def write_demo_homes(root: Path, chats: list[Chat], held: int = 0,
                     others: tuple[list[ClaudeChat], list[tuple[CursorChat, float]]] | None = None,
                     ) -> tuple[dict[str, Path], list[Path]]:
    """Write made-up Codex, Claude Code and Cursor homes under `root`; the first Codex chat holds back `held` records.

    `others` is the Claude Code chats and (Cursor chat, minutes since its last update) pairs; the README set by default.
    """
    homes = {name: root / name for name in ("codex", "claude", "cursor", "cursor-user")}
    paths = [chat.write(homes["codex"], held if index == 0 else 0) for index, chat in enumerate(chats)]
    (homes["codex"] / "session_index.jsonl").write_text(
        "".join(json.dumps({"id": c.id, "thread_name": c.title}) + "\n" for c in chats), encoding="utf-8")
    claude, cursor = others or demo_other_chats()
    for chat in claude:
        chat.write(homes["claude"])
    storage = homes["cursor-user"] / "globalStorage"
    storage.mkdir(parents=True)
    with sqlite3.connect(storage / "state.vscdb") as database:
        database.execute("CREATE TABLE composerHeaders (composerId TEXT UNIQUE, workspaceId TEXT, createdAt INTEGER,"
                         " lastUpdatedAt INTEGER, isArchived INTEGER, isSubagent INTEGER, value TEXT)")
        for chat, minutes_ago in cursor:
            chat.write(homes["cursor"], database, minutes_ago)
    database.close()
    return homes, paths


def serve_demo(root: Path, port: int) -> None:
    """Run a disposable app with its own reminder state as well as its own agent homes."""
    import uvicorn

    from yourturn.app import SHUTDOWN_SECONDS, create_app

    app = create_app(root / "codex", claude_home=root / "claude", cursor_home=root / "cursor",
                     cursor_user_dir=root / "cursor-user", state_path=root / "inbox-state.json")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning", timeout_graceful_shutdown=SHUTDOWN_SECONDS)


@contextmanager
def demo_server(chats: list[Chat], held: int = 0):
    """Serve disposable agent homes and inbox state. The first chat holds back `held` records."""
    with tempfile.TemporaryDirectory() as tmp:
        _, paths = write_demo_homes(Path(tmp), chats, held)
        port = free_port()
        server = subprocess.Popen([str(ROOT / ".venv" / "bin" / "python"), "-c",
            ("import sys; from pathlib import Path; from demo.server import serve_demo;"
             "serve_demo(Path(sys.argv[1]), int(sys.argv[2]))"), tmp, str(port)], cwd=ROOT)
        try:
            base = f"http://127.0.0.1:{port}"
            wait_for(base + "/", server)
            yield base, paths[0]
        finally:
            server.terminate()
            server.wait()

