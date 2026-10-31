"""Engine (TurnFolder / SessionHub), Codex adapter, and app id-alias tests on tmp_path fixtures only."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from yourturn.app import create_app
from yourturn.engine import SessionHub, TurnFolder
from yourturn.harness.codex import DECISION_TOOL, CodexAdapter, record_to_events
from yourturn.heuristics import QUIET_SECONDS
from yourturn.model import SessionKey, SessionRef
from yourturn.rollout import Sessions

SID = "019a2b3c-4d5e-7f60-8a9b-0c1d2e3f4a5b"
SID_B = "019a2b3c-4d5e-7f60-8a9b-0c1d2e3f4a5c"
UNKNOWN = "019a2b3c-4d5e-7f60-8a9b-0c1d2e3f4a5d"


def _ts(second: int) -> str:
    return f"2026-10-31T10:00:{second:02d}.000Z"


def _meta(sid: str, *, subagent: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {"id": sid, "cwd": "/work/repo", "timestamp": _ts(0), "cli_version": "0.50.0"}
    if subagent:
        payload["source"] = {"subagent": {"parent": SID}}
    return {"timestamp": _ts(0), "type": "session_meta", "payload": payload}


def _event(second: int, payload: dict[str, Any]) -> dict[str, Any]:
    return {"timestamp": _ts(second), "type": "event_msg", "payload": payload}


def _item(second: int, item: dict[str, Any]) -> dict[str, Any]:
    return _event(second, {"type": "item_completed", "item": item})


def _turn(start: int = 1, turn_id: str = "t1") -> list[dict[str, Any]]:
    """One complete turn: prompt, a check command, an edit, a final answer, usage, completion."""
    return [
        {"timestamp": _ts(start), "type": "turn_context", "payload": {"model": "gpt-5"}},
        _event(start, {"type": "task_started", "turn_id": turn_id}),
        _item(start + 1, {"type": "UserMessage", "content": [{"type": "text", "text": "Fix the bug"}]}),
        _item(start + 2, {"type": "CommandExecution", "command": ["bash", "-lc", "uv run pytest"], "exit_code": 0}),
        _item(start + 3, {"type": "FileChange", "changes": {"src/app.py": {}}, "status": "completed"}),
        _item(start + 4, {"type": "AgentMessage", "content": [{"type": "text", "text": "Done."}]}),
        _event(
            start + 5,
            {"type": "token_count", "info": {"total_token_usage": {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15}}},
        ),
        _event(start + 6, {"type": "task_complete", "turn_id": turn_id}),
    ]


def _lines(records: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(record) + "\n" for record in records)


def _write(home: Path, sid: str, records: list[dict[str, Any]]) -> Path:
    day = home / "sessions" / "2026" / "10" / "31"
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"rollout-2026-10-31T10-00-00-{sid}.jsonl"
    path.write_text(_lines(records), encoding="utf-8")
    return path


def _events(records: list[dict[str, Any]]) -> list[Any]:
    return [event for record in records for event in record_to_events(record)]


def _ref(sid: str = SID) -> SessionRef:
    return SessionRef(harness="codex", session_id=sid)


# --- TurnFolder ----------------------------------------------------------------------------------


def test_folder_completed_turn() -> None:
    folder = TurnFolder(_ref())
    events = _events([_meta(SID), *_turn()])
    folder.fold_many(events)

    assert folder.version == len(events)
    assert folder.status == "done"
    assert folder.cwd == "/work/repo"
    assert folder.model == "gpt-5"
    turn = folder.turns[-1]
    assert turn.index == 1
    assert turn.status == "done"
    assert turn.ended_at == _ts(7)
    assert turn.prompt == "Fix the bug"
    assert turn.files == ["src/app.py"]
    assert folder.usage is not None and folder.usage.total_tokens == 15
    kinds = [step.kind for step in folder.steps]
    assert kinds[0] == "turn" and kinds[-1] == "turn"
    assert {"user", "command", "edit"} <= set(kinds)
    # The turn's last agent message is promoted to its final answer.
    assert "answer" in kinds and "message" not in kinds


def test_folder_aborted_turn_is_interrupted() -> None:
    folder = TurnFolder(_ref())
    folder.fold_many(
        _events([_event(1, {"type": "task_started", "turn_id": "t1"}), _event(2, {"type": "turn_aborted", "turn_id": "t1", "reason": "interrupted"})])
    )
    assert folder.status == "interrupted"
    assert folder.turns[-1].status == "interrupted"
    assert folder.steps[-1].status == "failed"


def test_folder_new_turn_closes_open_turn() -> None:
    folder = TurnFolder(_ref())
    folder.fold_many(_events([_event(1, {"type": "task_started", "turn_id": "t1"}), _event(2, {"type": "task_started", "turn_id": "t2"})]))
    assert [turn.index for turn in folder.turns] == [1, 2]
    assert folder.turns[0].status == "interrupted"
    assert folder.status == "working"


def test_folder_mid_turn_tail_creates_turn_lazily() -> None:
    folder = TurnFolder(_ref())
    folder.fold_many(_events([_item(1, {"type": "AgentMessage", "content": [{"type": "text", "text": "Working on it"}]})]))
    assert len(folder.turns) == 1 and folder.turns[0].index == 0
    assert folder.status == "working"


def test_folder_question_waits_then_user_answers() -> None:
    folder = TurnFolder(_ref())
    question = {"title": "Pick one", "options": ["a", "b"]}
    folder.fold_many(
        _events(
            [
                _event(1, {"type": "task_started", "turn_id": "t1"}),
                _item(2, {"type": "AgentMessage", "content": [{"type": "text", "text": "Which?"}], "questions": [question]}),
                _event(3, {"type": "task_complete", "turn_id": "t1"}),
            ]
        )
    )
    assert folder.status == "waiting"
    assert folder.decisions[-1].question == "Pick one"
    assert folder.decisions[-1].chosen is None
    assert folder.inbox_row()["question"] == "Pick one"

    folder.fold_many(_events([_item(4, {"type": "UserMessage", "content": [{"type": "text", "text": "a"}]})]))
    assert folder.decisions[-1].chosen == "a"


# --- CodexAdapter --------------------------------------------------------------------------------


def test_adapter_discovers_rollouts(tmp_path: Path) -> None:
    path = _write(tmp_path, SID, [_meta(SID), *_turn()])
    (tmp_path / "sessions" / "notes.jsonl").write_text("{}\n", encoding="utf-8")
    refs = list(CodexAdapter(home=tmp_path).discover())
    assert refs == [SessionRef(harness="codex", session_id=SID, path=path, cwd="/work/repo")]
    # A root pointing at the Codex home (or at sessions/ itself) finds the same files.
    assert [ref.session_id for ref in CodexAdapter().discover(tmp_path)] == [SID]
    assert [ref.session_id for ref in CodexAdapter().discover(tmp_path / "sessions")] == [SID]


def test_adapter_skips_subagents_unless_asked(tmp_path: Path) -> None:
    _write(tmp_path, SID, [_meta(SID)])
    _write(tmp_path, SID_B, [_meta(SID_B, subagent=True)])
    assert {ref.session_id for ref in CodexAdapter(home=tmp_path).discover()} == {SID}
    assert {ref.session_id for ref in CodexAdapter(home=tmp_path, include_subagents=True).discover()} == {SID, SID_B}


def test_adapter_parses_events(tmp_path: Path) -> None:
    _write(tmp_path, SID, [_meta(SID), *_turn()])
    adapter = CodexAdapter(home=tmp_path)
    (ref,) = adapter.discover()
    events = adapter.open(ref).read_new()
    names = [type(event).__name__ for event in events]
    assert names == ["Meta", "Meta", "TurnStarted", "UserMessage", "CommandRun", "FilesEdited", "AgentMessage", "Usage", "TurnEnded"]
    assert events[4].command == "uv run pytest" and events[4].exit_code == 0
    assert events[5].paths == ("src/app.py",)


def test_adapter_skips_malformed_and_waits_for_partial_lines(tmp_path: Path) -> None:
    path = _write(tmp_path, SID, [_meta(SID)])
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"type": "event_msg", "payload": {"type": "task_started"\n')  # truncated JSON
        handle.write('not json at all "task_started"\n')
        handle.write('["task_started"]\n')  # valid JSON, not a record
        handle.write(json.dumps(_event(1, {"type": "task_started", "turn_id": "t1"})) + "\n")
        handle.write(json.dumps(_event(2, {"type": "task_complete", "turn_id": "t1"})))  # no newline yet
    adapter = CodexAdapter(home=tmp_path)
    (ref,) = adapter.discover()
    cursor = adapter.open(ref)
    assert [type(event).__name__ for event in cursor.read_new()] == ["Meta", "TurnStarted"]
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n")
    assert [type(event).__name__ for event in cursor.read_new()] == ["TurnEnded"]
    assert cursor.read_new() == []


def test_adapter_title_from_session_index(tmp_path: Path) -> None:
    _write(tmp_path, SID, [_meta(SID)])
    (tmp_path / "session_index.jsonl").write_text(json.dumps({"id": SID, "thread_name": "My chat"}) + "\nnot json\n", encoding="utf-8")
    adapter = CodexAdapter(home=tmp_path)
    (ref,) = adapter.discover()
    assert adapter.title(ref) == "My chat"


# --- SessionHub ----------------------------------------------------------------------------------


def _hub(home: Path) -> SessionHub:
    return SessionHub([CodexAdapter(home=home)], root=home, rescan_seconds=0.0)


def test_hub_lists_threads(tmp_path: Path) -> None:
    _write(tmp_path, SID, [_meta(SID), *_turn()])
    _write(tmp_path, SID_B, [_meta(SID_B)])
    snapshots = _hub(tmp_path).refresh()
    assert {snapshot.ref.session_id for snapshot in snapshots} == {SID, SID_B}
    done = next(snapshot for snapshot in snapshots if snapshot.ref.session_id == SID)
    assert done.phase == "done"
    assert done.title == "Fix the bug"
    assert done.recap.turn_count == 1


def test_hub_detail_accepts_prefixed_and_bare_ids(tmp_path: Path) -> None:
    _write(tmp_path, SID, [_meta(SID), *_turn()])
    hub = _hub(tmp_path)
    hub.refresh()
    prefixed = hub.detail(f"codex:{SID}")
    bare = hub.detail(SID)
    keyed = hub.detail(SessionKey.parse(SID))
    assert prefixed is not None and bare is not None and keyed is not None
    assert prefixed.snapshot.ref == bare.snapshot.ref == keyed.snapshot.ref
    assert prefixed.timeline == bare.timeline and prefixed.timeline
    assert prefixed.handoff.resume_command == f"codex resume {SID}"


def test_hub_unknown_or_malformed_ids_are_none(tmp_path: Path) -> None:
    _write(tmp_path, SID, [_meta(SID)])
    hub = _hub(tmp_path)
    hub.refresh()
    assert hub.detail(UNKNOWN) is None
    assert hub.detail(f"codex:{UNKNOWN}") is None
    assert hub.detail(f"claude:{SID}") is None
    assert hub.detail("not-a-session") is None
    assert hub.detail("bogus:123") is None


def test_hub_refresh_reads_appended_turns(tmp_path: Path) -> None:
    path = _write(tmp_path, SID, [_meta(SID), *_turn(1, "t1")])
    hub = _hub(tmp_path)
    hub.refresh()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(_lines(_turn(20, "t2")))
    (snapshot,) = hub.refresh()
    assert snapshot.recap.turn_count == 2


# --- App -----------------------------------------------------------------------------------------


def _client(home: Path) -> TestClient:
    app = create_app(home, poll_seconds=0.01, should_stop=lambda: True)
    return TestClient(app, base_url="http://localhost")


def test_app_thread_accepts_prefixed_and_bare_ids(tmp_path: Path) -> None:
    _write(tmp_path, SID, [_meta(SID), *_turn()])
    client = _client(tmp_path)
    bare = client.get(f"/api/threads/{SID}")
    prefixed = client.get(f"/api/threads/codex:{SID}")
    assert bare.status_code == 200, bare.text
    assert prefixed.status_code == 200, prefixed.text
    assert prefixed.json() == bare.json()


def test_app_thread_rejects_malformed_ids(tmp_path: Path) -> None:
    client = _client(tmp_path)
    for bad in ("garbage", "codex:garbage", "bogus:" + SID, "CODEX:" + SID):
        assert client.get(f"/api/threads/{bad}").status_code == 400, bad


def test_app_thread_unknown_is_404(tmp_path: Path) -> None:
    _write(tmp_path, SID, [_meta(SID), *_turn()])
    client = _client(tmp_path)
    assert client.get(f"/api/threads/{UNKNOWN}").status_code == 404
    assert client.get(f"/api/threads/codex:{UNKNOWN}").status_code == 404
    assert client.get(f"/api/threads/claude:{SID}").status_code == 404


def test_app_stream_validates_thread_and_stops(tmp_path: Path) -> None:
    _write(tmp_path, SID, [_meta(SID), *_turn()])
    client = _client(tmp_path)
    # should_stop() is already True, so each stream closes immediately instead of polling forever.
    assert client.get("/api/stream", params={"thread": f"codex:{SID}"}).status_code == 200
    assert client.get("/api/stream", params={"thread": SID}).status_code == 200
    assert client.get("/api/stream", params={"thread": "garbage"}).status_code == 400


# --- API dict parity (the JSON contract app.js reads) -------------------------------------------

OLD = "019a2b3c-4d5e-7f60-8a9b-0c1d2e3f4a5e"

INBOX_KEYS = {
    "id", "cwd", "status", "updated_at", "turn_ended_at", "outcome", "next_kind", "next_text",
    "question", "options", "attention_key", "check_state", "needs_you", "quiet", "project", "title",
}
DETAIL_KEYS = {
    "id", "title", "cwd", "project", "parent_id", "subagent", "started_at", "updated_at", "status",
    "context_used", "context_window", "token_usage", "last_token_usage", "token_usage_at", "model",
    "reasoning_effort", "model_provider", "git_branch", "cli_version", "activity", "attention_key",
    "version", "turns", "steps", "decisions", "needs_you", "quiet", "capabilities",
}
TURN_KEYS = {
    "index", "started_at", "ended_at", "status", "prompt", "outcome", "recap", "next_kind", "next_text",
    "formatted", "files", "checks", "edited_after_check",
}
CHECK_KEYS = {"command", "exit_code", "at"}
STEP_KEYS = {"at", "kind", "title", "detail", "status", "turn"}
DECISION_KEYS = {"at", "source", "question", "options", "chosen", "reason", "turn"}
EXTRA_KEYS = {"harness", "key", "handoff"}


def _rich_records() -> list[dict[str, Any]]:
    """Turn 1 completes (failed then passing check, code edit, agent decision, final answer, usage);
    turn 2 asks the user a question and waits; turn 3 is aborted."""
    meta = {
        "timestamp": _ts(0),
        "type": "session_meta",
        "payload": {"id": SID, "cwd": "/work/repo", "timestamp": _ts(0), "cli_version": "0.50.0",
                    "model_provider": "openai", "git": {"branch": "main"}},
    }
    decision = {"question": "Patch or rewrite?", "options": ["patch", "rewrite"], "chosen": "patch", "reason": "Smaller diff"}
    usage = {
        "total_token_usage": {"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 20, "total_tokens": 120},
        "last_token_usage": {"total_tokens": 60},
        "model_context_window": 1000,
    }
    return [
        meta,
        {"timestamp": _ts(1), "type": "turn_context", "payload": {"model": "gpt-5", "effort": "high"}},
        _event(1, {"type": "task_started", "turn_id": "t1"}),
        _item(2, {"type": "UserMessage", "content": [{"type": "text", "text": "Fix the bug"}]}),
        _item(3, {"type": "Reasoning", "summary_text": ["Reading the failing test"]}),
        _item(4, {"type": "CommandExecution", "command": ["bash", "-lc", "uv run pytest"], "exit_code": 1}),
        _item(5, {"type": "FileChange", "changes": {"src/app.py": {}}, "status": "completed"}),
        _item(6, {"type": "CommandExecution", "command": ["bash", "-lc", "uv run pytest"], "exit_code": 0}),
        _item(7, {"type": "McpToolCall", "server": "your-turn", "tool": DECISION_TOOL, "status": "completed", "arguments": decision}),
        _item(8, {"type": "AgentMessage", "phase": "final_answer",
                  "content": [{"type": "text", "text": "Outcome: Fixed the bug.\nNext step: review: the diff"}]}),
        _event(9, {"type": "token_count", "info": usage}),
        _event(10, {"type": "task_complete", "turn_id": "t1", "duration_ms": 9000}),
        _event(11, {"type": "task_started", "turn_id": "t2"}),
        _item(12, {"type": "AgentMessage", "content": [{"type": "text", "text": "One question first."}],
                   "questions": [{"title": "Ship now?", "options": ["Yes", "No"]}]}),
        _event(13, {"type": "task_complete", "turn_id": "t2"}),
        _event(14, {"type": "task_started", "turn_id": "t3"}),
        _event(15, {"type": "turn_aborted", "turn_id": "t3", "reason": "interrupted"}),
    ]


def _age(path: Path, seconds: float) -> None:
    then = time.time() - seconds
    os.utime(path, (then, then))


def _rich_home(home: Path) -> Path:
    """The rich chat (fresh), a quiet working chat (no writes for a while), and one outside the history window."""
    path = _write(home, SID, _rich_records())
    quiet = _write(home, SID_B, [_meta(SID_B), _event(1, {"type": "task_started", "turn_id": "t1"})])
    old = _write(home, OLD, [_meta(OLD), *_turn()])
    _age(quiet, QUIET_SECONDS + 60)
    _age(old, 1000 * 86400)
    (home / "session_index.jsonl").write_text(json.dumps({"id": SID, "thread_name": "Rich chat"}) + "\n", encoding="utf-8")
    return path


def _without_extras(data: dict[str, Any]) -> dict[str, Any]:
    return {name: value for name, value in data.items() if name not in EXTRA_KEYS}


def test_inbox_dict_keys_and_values(tmp_path: Path) -> None:
    _rich_home(tmp_path)
    rows = SessionHub.for_codex_home(tmp_path, scan_ttl=0).inbox_dicts()

    assert [row["id"] for row in rows] == [SID, SID_B], "newest file first; out-of-window chats are skipped"
    for row in rows:
        assert set(row) == INBOX_KEYS | EXTRA_KEYS
        assert (row["harness"], row["key"]) == ("codex", f"codex:{row['id']}")
        assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ", row["updated_at"])
        assert isinstance(row["needs_you"], bool) and isinstance(row["quiet"], bool)
        assert isinstance(row["options"], list) and isinstance(row["check_state"], str)
    rich, quiet = rows
    assert (rich["status"], rich["cwd"], rich["project"], rich["title"]) == ("interrupted", "/work/repo", "repo", "Rich chat")
    assert (rich["question"], rich["options"]) == ("Ship now?", ["Yes", "No"])
    assert (rich["turn_ended_at"], rich["next_kind"], rich["outcome"], rich["attention_key"]) == (_ts(15), "unknown", "", "")
    assert rich["quiet"] is False
    assert (quiet["status"], quiet["quiet"], quiet["title"]) == ("working", True, "")


def test_detail_dict_keys_and_values(tmp_path: Path) -> None:
    _rich_home(tmp_path)
    data = SessionHub.for_codex_home(tmp_path, scan_ttl=0).detail_dict(SID)

    assert data is not None
    assert set(data) == DETAIL_KEYS | EXTRA_KEYS
    assert (data["harness"], data["key"]) == ("codex", f"codex:{SID}")
    assert all(set(turn) == TURN_KEYS for turn in data["turns"])
    assert all(set(check) == CHECK_KEYS for turn in data["turns"] for check in turn["checks"])
    assert all(set(step) == STEP_KEYS for step in data["steps"])
    assert all(set(decision) == DECISION_KEYS for decision in data["decisions"])

    assert data["version"] == len(_rich_records())
    assert (data["title"], data["project"], data["status"], data["quiet"]) == ("Rich chat", "repo", "interrupted", False)
    assert (data["started_at"], data["updated_at"], data["subagent"], data["parent_id"]) == (_ts(0), _ts(15), False, "")
    assert (data["model"], data["reasoning_effort"], data["model_provider"], data["git_branch"], data["cli_version"]) == (
        "gpt-5", "high", "openai", "main", "0.50.0")
    assert data["token_usage"] == {"input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 20, "total_tokens": 120}
    assert (data["last_token_usage"], data["token_usage_at"], data["context_used"], data["context_window"]) == (
        {"total_tokens": 60}, _ts(9), 60, 1000)
    assert isinstance(data["needs_you"], bool)

    first, second, third = data["turns"]
    assert (first["index"], first["status"], first["prompt"], first["files"]) == (1, "done", "Fix the bug", ["src/app.py"])
    assert first["checks"] == [{"command": "uv run pytest", "exit_code": 0, "at": _ts(6)}]
    assert first["edited_after_check"] is False
    assert (first["outcome"], first["next_kind"], first["next_text"], first["formatted"]) == ("Fixed the bug.", "review", "the diff", True)
    assert (second["status"], second["next_kind"], second["next_text"]) == ("waiting", "answer", "Ship now?")
    assert (third["status"], third["ended_at"]) == ("interrupted", _ts(15))

    kinds = [step["kind"] for step in data["steps"]]
    assert kinds == ["turn", "user", "thinking", "command", "edit", "command", "decision", "answer", "turn",
                     "turn", "message", "question", "turn", "turn", "turn"]
    finished = data["steps"][8]
    assert (finished["title"], finished["detail"], finished["turn"]) == ("Turn 1 finished", "9s", 1)
    assert (data["steps"][-1]["title"], data["steps"][-1]["status"]) == ("Turn 3 stopped", "failed")
    agent, asked = data["decisions"]
    assert (agent["source"], agent["chosen"], agent["reason"], agent["turn"]) == ("agent", "patch", "Smaller diff", 1)
    assert (asked["source"], asked["question"], asked["options"], asked["chosen"]) == ("asked", "Ship now?", ["Yes", "No"], None)


def test_sessions_facade_returns_hub_dicts(tmp_path: Path) -> None:
    _rich_home(tmp_path)
    hub = SessionHub.for_codex_home(tmp_path, scan_ttl=0)
    sessions = Sessions(tmp_path, scan_ttl=0)
    assert sessions.inbox() == hub.inbox_dicts()
    assert sessions.snapshot(SID) == hub.detail_dict(SID)
    assert sessions.state(SID) is not None and sessions.state(SID).version == len(_rich_records())
    # Both have read the inbox above, so both know which chats are quiet.
    assert sessions.inbox_fingerprint() == hub.inbox_fingerprint()


def test_api_json_equals_hub_dicts(tmp_path: Path) -> None:
    _rich_home(tmp_path)
    client = _client(tmp_path)
    hub = SessionHub.for_codex_home(tmp_path, scan_ttl=0)

    for raw in (SID, f"codex:{SID}"):
        response = client.get(f"/api/threads/{raw}")
        assert response.status_code == 200, response.text
        expected = hub.detail_dict(raw)
        assert expected is not None
        assert _without_extras(response.json()) == _without_extras(json.loads(json.dumps(expected)))
        assert response.json()["key"] == f"codex:{SID}"
    assert client.get("/api/inbox").json() == json.loads(json.dumps(hub.inbox_dicts()))


def test_hub_typed_detail_shares_the_detail_state(tmp_path: Path) -> None:
    _rich_home(tmp_path)
    hub = SessionHub.for_codex_home(tmp_path, scan_ttl=0)
    data = hub.detail_dict(SID)
    detail = hub.detail(f"codex:{SID}")
    assert data is not None and detail is not None
    assert len(detail.timeline) == len(data["steps"])
    assert detail.snapshot.title == "Rich chat"
    assert detail.snapshot.recap.turn_count == 3
    assert detail.handoff.resume_command == f"codex resume {SID}"


def test_version_and_fingerprint_change_only_on_append(tmp_path: Path) -> None:
    path = _rich_home(tmp_path)
    hub = SessionHub.for_codex_home(tmp_path, scan_ttl=0)
    hub.inbox_dicts()
    fingerprint = hub.inbox_fingerprint()
    before = hub.detail_dict(SID)
    assert before is not None

    # Nothing changed: same version, same marker.
    again = hub.detail_dict(SID)
    assert again is not None and again["version"] == before["version"]
    assert hub.inbox_fingerprint() == fingerprint

    appended = _turn(20, "t4")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(_lines(appended))

    assert hub.inbox_fingerprint() != fingerprint
    after = hub.detail_dict(SID)
    assert after is not None and after["version"] == before["version"] + len(appended)
    assert after["turns"][-1]["index"] == 4 and after["status"] == "done"
    hub.inbox_dicts()
    settled = hub.inbox_fingerprint()
    assert hub.inbox_fingerprint() == settled
    final = hub.detail_dict(SID)
    assert final is not None and final["version"] == after["version"]
