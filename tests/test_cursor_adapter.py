"""Cursor adapter tests on synthetic transcripts and a synthetic state.vscdb under tmp_path."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from yourturn.app import create_app
from yourturn.engine import SessionHub, TurnFolder
from yourturn.harness.base import ApprovalPending, CommandRun, FilesEdited, Meta, ToolCall, TurnEnded, TurnStarted, UserMessage
from yourturn.harness.cursor import CursorAdapter, CursorCursor, decode_slug, parse_prompt_time, prompt_text
from yourturn.model import SessionRef

CID = "9f1c2b3a-4d5e-4f60-8a9b-0c1d2e3f4a5b"
ARCHIVED = "9f1c2b3a-4d5e-4f60-8a9b-0c1d2e3f4a5c"
CWD = "/work/my-repo"
STAMP = "<timestamp>Friday, Oct 31, 2026, 9:05 AM (UTC+2)</timestamp>"
FINAL = "Outcome: Fixed the bug.\nNext step: review: the diff"


def user(text: str, stamp: str = STAMP) -> dict[str, Any]:
    return {"role": "user", "message": {"content": [{"type": "text", "text": f"{stamp}\n<user_query>\n{text}\n</user_query>"}]}}


def assistant(*blocks: dict[str, Any]) -> dict[str, Any]:
    return {"role": "assistant", "message": {"content": list(blocks)}}


def text(value: str) -> dict[str, Any]:
    return {"type": "text", "text": value}


def tool(name: str, arguments: Any) -> dict[str, Any]:
    return {"type": "tool_use", "name": name, "input": arguments}


ENDED = {"type": "turn_ended", "status": "success"}
ASK = tool("AskQuestion", {"questions": [{"id": "q", "prompt": "Ship now?", "allow_multiple": False,
                                          "options": [{"id": "y", "label": "Yes"}, {"id": "n", "label": "No"}]}]})


def _turn() -> list[dict[str, Any]]:
    """prompt -> passing check -> edit + patch -> answered question -> final answer."""
    return [
        user("Fix the bug"),
        assistant(text("Running the tests."), tool("Shell", {"command": "uv run pytest -q\necho ok", "description": "tests"})),
        assistant(tool("StrReplace", {"path": f"{CWD}/src/app.py", "old_string": "a", "new_string": "b"}),
                  tool("ApplyPatch", "*** Begin Patch\n*** Update File: src/util.py\n@@\n-a\n+b\n*** End Patch")),
        assistant(ASK),
        assistant(tool("CallMcpTool", {"server": "github", "toolName": "get_issue", "arguments": {"n": 1}}),
                  tool("Task", {"description": "Explore the repo", "subagent_type": "explore", "prompt": "..."})),
        assistant(text(FINAL)),
        ENDED,
    ]


def _write(home: Path, records: list[dict[str, Any]], cid: str = CID, slug: str = "work-my-repo") -> Path:
    folder = home / "projects" / slug / "agent-transcripts" / cid
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{cid}.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return path


def _database(user_dir: Path, rows: list[tuple[str, int, int, dict[str, Any]]]) -> Path:
    path = user_dir / "globalStorage" / "state.vscdb"
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE composerHeaders (composerId TEXT UNIQUE, workspaceId TEXT, createdAt INTEGER, lastUpdatedAt INTEGER,"
            " isArchived INTEGER, isSubagent INTEGER, recency INTEGER, checkpointAt INTEGER, value TEXT, subagentTypeName TEXT)"
        )
        connection.executemany(
            "INSERT INTO composerHeaders (composerId, workspaceId, isArchived, isSubagent, value) VALUES (?, 'w1', ?, ?, ?)",
            [(cid, archived, subagent, json.dumps(value)) for cid, archived, subagent, value in rows],
        )
    connection.close()
    return path


def _header(name: str, cwd: str = CWD, *, pending: bool = False, updated: int = 1793430300000) -> dict[str, Any]:
    return {"composerId": CID, "name": name, "createdAt": 1793430000000, "lastUpdatedAt": updated,
            "hasBlockingPendingActions": pending,
            "workspaceIdentifier": {"id": "w1", "uri": {"fsPath": cwd, "path": cwd, "scheme": "file"}}}


def _home(tmp_path: Path) -> tuple[Path, Path]:
    home, user_dir = tmp_path / "cursor", tmp_path / "User"
    _write(home, _turn())
    _write(home, [user("old work"), ENDED], cid=ARCHIVED)
    _database(user_dir, [(CID, 0, 0, _header("Fix parser")), (ARCHIVED, 1, 0, _header("Archived chat"))])
    return home, user_dir


def _fold(path: Path, title: str = "") -> TurnFolder:
    ref = SessionRef(harness="cursor", session_id=path.stem, path=path, cwd=CWD)
    folder = TurnFolder(ref)
    folder.fold_many(CursorCursor(ref, title).read_new())
    return folder


# --- parsing helpers -----------------------------------------------------------------------------


def test_prompt_parsing() -> None:
    assert prompt_text(f"{STAMP}\n<user_query>\n Fix it \n</user_query>") == "Fix it"
    assert prompt_text("<attached_files>x</attached_files>\nplain words") == "plain words"
    assert prompt_text(STAMP) == ""
    stamp = parse_prompt_time(STAMP)
    assert stamp is not None and stamp.isoformat() == "2026-10-31T09:05:00+02:00"
    assert parse_prompt_time("<timestamp>soon</timestamp>") is None


def test_decode_slug_resolves_existing_dashed_folders(tmp_path: Path) -> None:
    repo = tmp_path / "dev" / "my-repo"
    repo.mkdir(parents=True)
    assert decode_slug(str(repo).lstrip("/").replace("/", "-")) == str(repo)
    assert decode_slug("no-such-folder-anywhere") is None


# --- discovery -----------------------------------------------------------------------------------


def test_missing_home_discovers_nothing(tmp_path: Path) -> None:
    adapter = CursorAdapter(home=tmp_path / "none", user_dir=tmp_path / "none")
    assert adapter.available() is False and list(adapter.discover()) == []


def test_discover_uses_headers_and_skips_archived_and_subagents(tmp_path: Path) -> None:
    home, user_dir = _home(tmp_path)
    nested = home / "projects" / "work-my-repo" / "agent-transcripts" / CID / "subagents"
    nested.mkdir()
    (nested / "sub.jsonl").write_text(json.dumps(user("sub")) + "\n", encoding="utf-8")
    database = user_dir / "globalStorage" / "state.vscdb"
    before = database.read_bytes()

    adapter = CursorAdapter(home=home, user_dir=user_dir)
    (ref,) = adapter.discover()
    assert (ref.harness, ref.session_id, ref.cwd) == ("cursor", CID, CWD)
    assert (adapter.title(ref), adapter.project(ref)) == ("Fix parser", "my-repo")
    # Strictly read-only: the database is byte-for-byte unchanged and no journal appeared.
    assert database.read_bytes() == before
    assert sorted(p.name for p in database.parent.iterdir()) == ["state.vscdb"]


def test_discover_without_database_falls_back_to_the_folder_slug(tmp_path: Path) -> None:
    repo = tmp_path / "dev" / "my-repo"
    repo.mkdir(parents=True)
    home = tmp_path / "cursor"
    _write(home, _turn(), slug=str(repo).lstrip("/").replace("/", "-"))
    (ref,) = CursorAdapter(home=home, user_dir=tmp_path / "no-user-dir").discover()
    assert ref.cwd == str(repo)


def test_handoff_opens_the_project_in_cursor(tmp_path: Path) -> None:
    handoff = CursorAdapter(home=tmp_path).handoff(SessionRef(harness="cursor", session_id=CID, cwd="/work/my repo"), None)
    assert (handoff.open_path, handoff.open_uri, handoff.resume_command) == (
        "/work/my repo", "cursor://file/work/my%20repo", "cursor '/work/my repo'")


# --- events --------------------------------------------------------------------------------------


def test_cursor_emits_normalized_events(tmp_path: Path) -> None:
    path = _write(tmp_path, _turn())
    events = CursorCursor(SessionRef(harness="cursor", session_id=CID, path=path, cwd=CWD), "Fix parser").read_new()

    meta = events[0]
    assert isinstance(meta, Meta) and (meta.cwd, meta.title, meta.harness, meta.model_provider) == (CWD, "Fix parser", "cursor", "cursor")
    assert [type(event) for event in events[1:3]] == [TurnStarted, UserMessage]
    assert events[1].ts is not None and events[1].ts.isoformat() == "2026-10-31T09:05:00+02:00"
    (run,) = [event for event in events if isinstance(event, CommandRun)]
    assert (run.command, run.exit_code) == ("uv run pytest -q", None)
    assert [event.paths for event in events if isinstance(event, FilesEdited)] == [(f"{CWD}/src/app.py",), ("src/util.py",)]
    names = [event.name for event in events if isinstance(event, ToolCall)]
    assert names == ["ask_user", "github · get_issue", "subagent"]
    answered = [event for event in events if isinstance(event, UserMessage) and event.answers]
    assert answered[0].answers == (("Ship now?", ""),)
    # The last turn end is stamped with the transcript's last write, not the prompt time.
    assert isinstance(events[-1], TurnEnded) and events[-1].ts is not None and events[-1].ts != events[1].ts


def test_full_turn_folds_into_a_done_turn(tmp_path: Path) -> None:
    folder = _fold(_write(tmp_path, _turn()), "Fix parser")
    (turn,) = folder.turns
    assert (folder.status, folder.title, turn.prompt) == ("done", "Fix parser", "Fix the bug")
    assert turn.files == [f"{CWD}/src/app.py", "src/util.py"]
    assert [(check.command, check.exit_code) for check in turn.checks] == [("uv run pytest -q", None)]
    assert (turn.outcome, turn.next_kind, turn.next_text) == ("Fixed the bug.", "review", "the diff")
    (decision,) = folder.decisions
    # Answered (no longer pending), but Cursor does not record the answer text.
    assert (decision.question, decision.chosen) == ("Ship now?", "")
    assert folder.inbox_fields()["needs_you"] is True


def test_open_question_waits_and_failed_turn_is_interrupted(tmp_path: Path) -> None:
    waiting = _fold(_write(tmp_path / "a", [user("Release?"), assistant(text("One question."), ASK)]))
    row = waiting.inbox_fields()
    assert (waiting.status, row["question"], row["options"], row["needs_you"]) == ("waiting", "Ship now?", ["Yes", "No"], True)

    failed = _fold(_write(tmp_path / "b", [user("Go"), assistant(text("Trying")), {"type": "turn_ended", "status": "error", "error": "aborted"}]))
    assert (failed.status, failed.steps[-1].title, failed.steps[-1].status) == ("interrupted", "Turn 1 stopped", "failed")


def test_incremental_reads_only_return_appended_records(tmp_path: Path) -> None:
    path = _write(tmp_path, [user("First")])
    cursor = CursorCursor(SessionRef(harness="cursor", session_id=CID, path=path, cwd=CWD))
    assert [type(event) for event in cursor.read_new()] == [Meta, TurnStarted, UserMessage]
    assert cursor.read_new() == []
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(assistant(text("Done."))) + "\n" + json.dumps(ENDED) + "\n")
    assert [type(event).__name__ for event in cursor.read_new()] == ["AgentMessage", "TurnEnded"]


# --- hub and API ---------------------------------------------------------------------------------


def test_hub_and_api_serve_cursor_sessions(tmp_path: Path) -> None:
    home, user_dir = _home(tmp_path)
    codex_home = tmp_path / "codex"
    (codex_home / "sessions").mkdir(parents=True)

    hub = SessionHub.for_codex_home(codex_home, scan_ttl=0, cursor_home=home, cursor_user_dir=user_dir)
    (row,) = hub.inbox_dicts()
    assert (row["key"], row["harness"], row["title"], row["project"], row["status"]) == (
        f"cursor:{CID}", "cursor", "Fix parser", "my-repo", "done")
    assert row["handoff"]["open_uri"] == "cursor://file/work/my-repo"

    client = TestClient(create_app(codex_home, cursor_home=home, cursor_user_dir=user_dir), base_url="http://127.0.0.1")
    response = client.get(f"/api/threads/cursor:{CID}")
    assert response.status_code == 200, response.text
    data = response.json()
    assert (data["key"], data["harness"], data["status"], data["started_at"]) == (
        f"cursor:{CID}", "cursor", "done", "2026-10-31T07:00:00.000Z")
    assert data["turns"][-1]["outcome"] == "Fixed the bug."
    assert client.get(f"/api/threads/cursor:{ARCHIVED}").status_code == 404
    assert [entry["key"] for entry in client.get("/api/inbox").json()] == [f"cursor:{CID}"]


# --- pending approvals (composerHeaders.hasBlockingPendingActions) -------------------------------


def _set_header(user_dir: Path, value: dict[str, Any]) -> None:
    """Simulate Cursor updating its own composer row (tests own this synthetic database)."""
    with sqlite3.connect(user_dir / "globalStorage" / "state.vscdb") as connection:
        connection.execute("UPDATE composerHeaders SET value = ? WHERE composerId = ?", (json.dumps(value), CID))
    connection.close()


def test_cursor_reports_each_approval_flip() -> None:
    header: dict[str, Any] = {}
    ref = SessionRef(harness="cursor", session_id=CID, path=Path("/missing.jsonl"))
    cursor = CursorCursor(ref, header=lambda: header)
    assert cursor.read_new() == []
    header.update(pending=True)
    (event,) = cursor.read_new()
    assert isinstance(event, ApprovalPending) and (event.pending, event.text) == (True, "Approve pending action in Cursor")
    assert cursor.read_new() == []
    header.update(pending=False)
    (event,) = cursor.read_new()
    assert isinstance(event, ApprovalPending) and event.pending is False


def test_pending_approval_needs_you_until_cursor_clears_it(tmp_path: Path) -> None:
    home, user_dir = tmp_path / "cursor", tmp_path / "User"
    _write(home, [user("Fix the bug"), assistant(text("All done.")), ENDED])
    _database(user_dir, [(CID, 0, 0, _header("Fix parser", pending=True))])
    codex_home = tmp_path / "codex"
    (codex_home / "sessions").mkdir(parents=True)
    hub = SessionHub.for_codex_home(codex_home, scan_ttl=0, cursor_home=home, cursor_user_dir=user_dir)
    assert CursorAdapter.capabilities.approval_prompts is True

    (row,) = hub.inbox_dicts()
    assert (row["status"], row["next_kind"], row["next_text"], row["needs_you"]) == (
        "waiting", "approve", "Approve pending action in Cursor", True)
    assert row["attention_key"]
    detail = hub.detail_dict(f"cursor:{CID}")
    assert detail is not None and (detail["status"], detail["needs_you"], detail["turns"][-1]["next_kind"]) == ("waiting", True, "approve")
    assert detail["steps"][-1]["title"] == "Approve pending action in Cursor"
    (snapshot,) = hub.snapshots()
    assert (snapshot.attention.value, snapshot.next_step.kind.value) == ("needs_you", "approve")
    waiting = hub.inbox_fingerprint()

    # The user approves in Cursor: only its database changes, the transcript does not.
    _set_header(user_dir, _header("Fix parser", pending=False, updated=1793430400000))
    assert hub.inbox_fingerprint() != waiting
    (row,) = hub.inbox_dicts()
    assert (row["status"], row["next_kind"], row["needs_you"], row["attention_key"]) == ("done", "unknown", False, "")
    detail = hub.detail_dict(f"cursor:{CID}")
    assert detail is not None and (detail["status"], detail["needs_you"]) == ("done", False)
