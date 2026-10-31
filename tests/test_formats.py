"""Contract tests: one anonymized sample of each file format the apps write, read through the whole API.

The samples in tests/fixtures/ keep the real record shapes, extra fields included, so a change in how
Your Turn reads Codex, Claude Code, or Cursor files fails here before it fails on a real machine.
"""

from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from yourturn.app import create_app

FIXTURES = Path(__file__).parent / "fixtures"
CODEX = "019a0000-0000-7000-8000-00000000c0de"
CLAUDE = "1b864749-0000-4000-8000-00000000c1a0"
CURSOR = "9f1c2b3a-0000-4000-8000-00000000c5a0"


def _copy(name: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / name, target)


def test_real_formats_read_through_the_api(tmp_path: Path) -> None:
    codex, claude, cursor, user_dir = (tmp_path / name for name in ("codex", "claude", "cursor", "User"))
    _copy("codex.jsonl", codex / "sessions/2026/10/31" / f"rollout-2026-10-31T12-00-00-{CODEX}.jsonl")
    _copy("codex-index.jsonl", codex / "session_index.jsonl")
    _copy("claude.jsonl", claude / "projects/-work-demo" / f"{CLAUDE}.jsonl")
    _copy("cursor.jsonl", cursor / "projects/work-demo/agent-transcripts" / CURSOR / f"{CURSOR}.jsonl")
    database = user_dir / "globalStorage" / "state.vscdb"
    database.parent.mkdir(parents=True)
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE composerHeaders (composerId TEXT UNIQUE, workspaceId TEXT, createdAt INTEGER,"
                           " lastUpdatedAt INTEGER, isArchived INTEGER, isSubagent INTEGER, recency INTEGER,"
                           " checkpointAt INTEGER, value TEXT, subagentTypeName TEXT)")
        connection.execute("INSERT INTO composerHeaders (composerId, workspaceId, isArchived, isSubagent, value) VALUES (?, 'w1', 0, 0, ?)",
                           (CURSOR, (FIXTURES / "cursor-header.json").read_text()))
    connection.close()
    app = TestClient(create_app(codex, claude_home=claude, cursor_home=cursor, cursor_user_dir=user_dir), base_url="http://127.0.0.1")

    rows = {row["key"]: row for row in app.get("/api/inbox").json()}
    assert {key: (row["title"], row["status"], row["check_state"], row["needs_you"]) for key, row in rows.items()} == {
        f"codex:{CODEX}": ("Fix login timeout", "done", "", True),
        f"claude:{CLAUDE}": ("Fix parser crash", "done", "", False),
        f"cursor:{CURSOR}": ("Add fetch retry", "done", "", False),
    }

    turns = {harness: app.get(f"/api/threads/{harness}:{sid}").json()["turns"][-1]
             for harness, sid in (("codex", CODEX), ("claude", CLAUDE), ("cursor", CURSOR))}
    shape = {harness: (turn["outcome"], turn["next_kind"], turn["formatted"], [Path(path).name for path in turn["files"]],
                       [check["command"] for check in turn["checks"]]) for harness, turn in turns.items()}
    assert shape == {
        "codex": ("Login works again.", "review", True, ["auth.py"], ["uv run pytest -q"]),
        "claude": ("The parser now skips the empty line that crashed it, and the tests pass.", "unknown", False,
                   ["parser.py"], ["uv run pytest -q"]),
        "cursor": ("The fetcher retries twice before failing.", "none", True, ["fetch.py"], ["uv run pytest -q"]),
    }
    assert [decision["chosen"] for decision in app.get(f"/api/threads/codex:{CODEX}").json()["decisions"]] == ["handler"]
