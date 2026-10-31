"""Claude Code adapter tests on synthetic transcripts under tmp_path (never the real ~/.claude)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from yourturn.engine import SessionHub, TurnFolder
from yourturn.harness.base import CommandRun, FilesEdited, Meta, Reasoning, TurnEnded, TurnStarted, Usage, UserMessage
from yourturn.harness.claude import ClaudeAdapter, ClaudeCursor, prompt_text
from yourturn.model import SessionKey, SessionRef

SID = "1b864749-81a0-464c-8486-67a7995d340e"
SID_B = "1b864749-81a0-464c-8486-67a7995d340f"
CWD = "/work/my-repo"


def _ts(second: int) -> str:
    return f"2026-10-31T10:00:{second:02d}.000Z"


def _base(second: int, kind: str, **extra: Any) -> dict[str, Any]:
    return {"type": kind, "timestamp": _ts(second), "sessionId": SID, "cwd": CWD, "gitBranch": "main",
            "version": "2.1.0", "isSidechain": False, "uuid": f"u{second}", **extra}


def user(second: int, content: Any, **extra: Any) -> dict[str, Any]:
    return _base(second, "user", message={"role": "user", "content": content}, **extra)


def assistant(second: int, block: dict[str, Any], stop: str = "tool_use", msg_id: str = "m1", usage: dict[str, int] | None = None) -> dict[str, Any]:
    message = {"model": "claude-opus-5-5", "id": msg_id, "role": "assistant", "content": [block], "stop_reason": stop,
               "usage": usage or {"input_tokens": 10, "cache_creation_input_tokens": 5, "cache_read_input_tokens": 100, "output_tokens": 20}}
    return _base(second, "assistant", message=message, effort="high")


def tool_use(tool_id: str, name: str, **arguments: Any) -> dict[str, Any]:
    return {"type": "tool_use", "id": tool_id, "name": name, "input": arguments}


def result(second: int, tool_id: str, content: str = "", is_error: bool = False) -> dict[str, Any]:
    return user(second, [{"type": "tool_result", "tool_use_id": tool_id, "content": content, "is_error": is_error}])


FINAL = "Outcome: Fixed the bug.\nNext step: review: the diff\nRecap: Patched the parser."


def _turn(final: str = FINAL) -> list[dict[str, Any]]:
    """prompt -> thinking -> passing check -> edit -> final answer."""
    return [
        {"type": "queue-operation", "operation": "enqueue", "timestamp": _ts(0), "sessionId": SID},
        user(1, "Fix the bug"),
        assistant(2, {"type": "thinking", "thinking": "Reading the failing test", "signature": "x"}),
        assistant(2, tool_use("t1", "Bash", command="uv run pytest -q\necho done")),
        result(3, "t1", "1 passed"),
        assistant(4, tool_use("t2", "Edit", file_path=f"{CWD}/src/app.py", old_string="a", new_string="b"), msg_id="m2"),
        result(5, "t2"),
        assistant(6, {"type": "text", "text": final}, stop="end_turn", msg_id="m3"),
        {"type": "custom-title", "customTitle": "Fix parser", "sessionId": SID},
    ]


def _write(home: Path, records: list[dict[str, Any]], sid: str = SID, slug: str = "-work-my-repo") -> Path:
    folder = home / "projects" / slug
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{sid}.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return path


def _fold(path: Path) -> TurnFolder:
    ref = SessionRef(harness="claude", session_id=path.stem, path=path, cwd=CWD)
    folder = TurnFolder(ref)
    folder.fold_many(ClaudeCursor(ref).read_new())
    return folder


# --- discovery -----------------------------------------------------------------------------------


def test_missing_home_is_unavailable_and_discovers_nothing(tmp_path: Path) -> None:
    adapter = ClaudeAdapter(home=tmp_path / "nope")
    assert adapter.available() is False
    assert list(adapter.discover()) == []


def test_discover_skips_subagents_and_sidechains(tmp_path: Path) -> None:
    main = _write(tmp_path, _turn())
    _write(tmp_path, [{**user(1, "side task"), "isSidechain": True}], sid=SID_B)
    nested = tmp_path / "projects" / "-work-my-repo" / SID / "subagents"
    nested.mkdir(parents=True)
    (nested / "agent-a1.jsonl").write_text(json.dumps(user(1, "sub")) + "\n", encoding="utf-8")

    adapter = ClaudeAdapter(home=tmp_path)
    assert adapter.available()
    (ref,) = adapter.discover()
    assert (ref.harness, ref.session_id, ref.path, ref.cwd) == ("claude", SID, main, CWD)
    assert adapter.project(ref) == "my-repo"
    assert ClaudeAdapter.project(SessionRef(harness="claude", session_id=SID, path=main)) == "repo"
    assert len(list(ClaudeAdapter(home=tmp_path, include_subagents=True).discover())) == 2


def test_handoff_resumes_the_session(tmp_path: Path) -> None:
    ref = SessionRef(harness="claude", session_id=SID, cwd=CWD)
    handoff = ClaudeAdapter(home=tmp_path).handoff(ref, None)
    assert (handoff.resume_command, handoff.terminal_cwd) == (f"claude --resume {SID}", CWD)


# --- events --------------------------------------------------------------------------------------


def test_cursor_emits_normalized_events(tmp_path: Path) -> None:
    path = _write(tmp_path, _turn())
    events = ClaudeCursor(SessionRef(harness="claude", session_id=SID, path=path)).read_new()

    meta = events[0]
    assert isinstance(meta, Meta)
    assert (meta.cwd, meta.git_branch, meta.model_provider, meta.subagent, meta.cli_version) == (CWD, "main", "anthropic", False, "2.1.0")
    assert [type(event) for event in events[1:4]] == [TurnStarted, UserMessage, Meta]
    assert (events[3].model, events[3].reasoning_effort) == ("claude-opus-5-5", "high")
    assert any(isinstance(event, Reasoning) and event.text == "Reading the failing test" for event in events)
    (run,) = [event for event in events if isinstance(event, CommandRun)]
    assert (run.command, run.exit_code, run.output_tail) == ("uv run pytest -q", 0, "1 passed")
    (edit,) = [event for event in events if isinstance(event, FilesEdited)]
    assert (edit.paths, edit.ok) == ((f"{CWD}/src/app.py",), True)
    assert isinstance(events[-2], TurnEnded) and events[-2].reason == "completed"
    assert isinstance(events[-1], Meta) and events[-1].title == "Fix parser"
    # Three API messages; m1's two blocks repeat its usage and count once.
    usages = [event for event in events if isinstance(event, Usage)]
    assert len(usages) == 3
    assert usages[-1].total == {"input_tokens": 345, "cached_input_tokens": 300, "output_tokens": 60, "total_tokens": 405}
    assert usages[-1].last["total_tokens"] == 135


def test_full_turn_folds_into_a_done_turn_with_parsed_answer(tmp_path: Path) -> None:
    folder = _fold(_write(tmp_path, _turn()))

    assert (folder.status, folder.title, folder.model, folder.model_provider, folder.git_branch) == (
        "done", "Fix parser", "claude-opus-5-5", "anthropic", "main")
    (turn,) = folder.turns
    assert (turn.index, turn.prompt, turn.files) == (1, "Fix the bug", [f"{CWD}/src/app.py"])
    assert [(check.command, check.exit_code) for check in turn.checks] == [("uv run pytest -q", 0)]
    assert turn.edited_after_check is True
    assert (turn.outcome, turn.next_kind, turn.next_text, turn.recap, turn.formatted) == (
        "Fixed the bug.", "review", "the diff", "Patched the parser.", True)
    assert [step.kind for step in folder.steps] == ["turn", "user", "thinking", "command", "edit", "answer", "turn"]
    assert folder.inbox_fields()["needs_you"] is True
    assert (folder.context_used, folder.token_usage["total_tokens"]) == (135, 405)


def test_plain_final_answer_has_no_next_step(tmp_path: Path) -> None:
    folder = _fold(_write(tmp_path, _turn("All done, tests pass.")))
    (turn,) = folder.turns
    assert (folder.status, turn.outcome, turn.next_kind, turn.formatted) == ("done", "All done, tests pass.", "unknown", False)
    assert folder.inbox_fields()["needs_you"] is False


def test_text_before_a_tool_call_does_not_end_the_turn(tmp_path: Path) -> None:
    folder = _fold(_write(tmp_path, [
        user(1, "Run the tests"),
        assistant(2, {"type": "text", "text": "Running them now."}),
        assistant(2, tool_use("t1", "Bash", command="pytest")),
        result(3, "t1", "FAILED", is_error=True),
    ]))
    (turn,) = folder.turns
    assert (folder.status, turn.ended_at) == ("working", "")
    assert [(check.command, check.exit_code) for check in turn.checks] == [("pytest", 1)]
    assert folder.steps[-1].status == "failed"


def test_question_waits_then_answer_resumes(tmp_path: Path) -> None:
    ask = tool_use("q1", "AskUserQuestion", questions=[
        {"question": "Ship now?", "header": "Ship", "multiSelect": False,
         "options": [{"label": "Yes", "description": "now"}, {"label": "No", "description": "later"}]}])
    records = [user(1, "Prepare the release"), assistant(2, ask)]
    path = _write(tmp_path, records)
    folder = _fold(path)
    row = folder.inbox_fields()
    assert (folder.status, row["question"], row["options"], row["needs_you"]) == ("waiting", "Ship now?", ["Yes", "No"], True)

    records += [result(3, "q1", 'User has answered your questions: "Ship now?"="Yes". You can now continue.'),
                assistant(4, {"type": "text", "text": "Shipped."}, stop="end_turn", msg_id="m2")]
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    folder = _fold(path)
    (decision,) = folder.decisions
    assert (decision.question, decision.chosen) == ("Ship now?", "Yes")
    assert folder.status == "done" and len(folder.turns) == 1
    assert [step.title for step in folder.steps if step.kind == "user"][-1] == "You answered: Yes"


def test_tools_mcp_subagents_and_interrupts(tmp_path: Path) -> None:
    decision = {"question": "Patch or rewrite?", "options": ["patch", "rewrite"], "chosen": "patch", "reason": "small"}
    folder = _fold(_write(tmp_path, [
        user(1, "Go"),
        assistant(2, tool_use("t1", "Task", description="Explore the repo", subagent_type="Explore")),
        assistant(2, tool_use("t2", "mcp__github__get_issue", number=1)),
        result(3, "t2", "{}"),
        assistant(4, tool_use("t3", "mcp__your-turn__log_decision", **decision)),
        result(5, "t3", "ok"),
        assistant(6, tool_use("t4", "Read", file_path="/x")),
        result(7, "t4", "nope", is_error=True),
        user(8, [{"type": "text", "text": "[Request interrupted by user]"}]),
    ]))
    titles = [(step.kind, step.title, step.status) for step in folder.steps]
    assert ("agent", "Sub-agent started: Explore the repo", "done") in titles
    assert ("tool", "github · get_issue", "done") in titles
    assert ("decision", "Patch or rewrite?", "done") in titles
    assert ("tool", "Read", "failed") in titles
    assert (folder.status, folder.turns[-1].status) == ("interrupted", "interrupted")


def test_injected_user_content_is_not_a_prompt(tmp_path: Path) -> None:
    assert prompt_text("<system-reminder>be nice</system-reminder>") == ""
    assert prompt_text("<local-command-stdout>ok</local-command-stdout>") == ""
    assert prompt_text("<command-message>review</command-message>\n<command-name>/review</command-name>") == "/review"
    folder = _fold(_write(tmp_path, [
        user(1, "<task-notification>done</task-notification>"),
        user(2, [{"type": "text", "text": "Caveat"}], isMeta=True),
        result(3, "unknown", "orphan"),
    ]))
    assert (list(folder.turns), list(folder.steps)) == ([], [])


def test_local_slash_command_is_a_finished_turn(tmp_path: Path) -> None:
    folder = _fold(_write(tmp_path, [
        user(1, "<command-name>/model</command-name>\n<command-message>model</command-message>"),
        user(2, "<local-command-stdout>Set model to opus</local-command-stdout>"),
    ]))
    (turn,) = folder.turns
    assert (turn.prompt, turn.status, folder.status) == ("/model", "done", "done")


def test_tail_read_keeps_header_and_appends_incrementally(tmp_path: Path) -> None:
    records = _turn()
    path = _write(tmp_path, records)
    cursor = ClaudeCursor(SessionRef(harness="claude", session_id=SID, path=path))
    cursor.seek(len(path.read_bytes()) - len(json.dumps(records[-1])) - 30)
    events = cursor.read_new()
    assert isinstance(events[0], Meta) and events[0].cwd == CWD
    assert cursor.read_new() == []
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(user(9, "Next task")) + "\n")
    assert [type(event) for event in cursor.read_new()] == [TurnStarted, UserMessage]


def test_hub_registers_claude_next_to_codex(tmp_path: Path) -> None:
    codex_home, claude = tmp_path / "codex", tmp_path / "claude"
    (codex_home / "sessions").mkdir(parents=True)
    _write(claude, _turn())

    assert SessionHub.for_codex_home(codex_home, scan_ttl=0).refresh() == []
    hub = SessionHub.for_codex_home(codex_home, scan_ttl=0, claude_home=claude)
    (snapshot,) = hub.refresh()
    assert (snapshot.ref.harness, snapshot.title, snapshot.phase.value) == ("claude", "Fix parser", "done")
    detail = hub.detail(SessionKey.parse(f"claude:{SID}"))
    assert detail is not None and detail.handoff.resume_command == f"claude --resume {SID}"
