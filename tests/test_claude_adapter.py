"""Claude Code adapter tests on synthetic transcripts under tmp_path (never the real ~/.claude)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from yourturn.engine import SessionHub, TurnFolder
from yourturn.heuristics import QUIET_SECONDS
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


def test_missing_home_discovers_nothing(tmp_path: Path) -> None:
    assert list(ClaudeAdapter(home=tmp_path / "nope").discover()) == []


def test_discover_skips_subagents_and_sidechains(tmp_path: Path) -> None:
    main = _write(tmp_path, _turn())
    _write(tmp_path, [{**user(1, "side task"), "isSidechain": True}], sid=SID_B)
    nested = tmp_path / "projects" / "-work-my-repo" / SID / "subagents"
    nested.mkdir(parents=True)
    (nested / "agent-a1.jsonl").write_text(json.dumps(user(1, "sub")) + "\n", encoding="utf-8")

    adapter = ClaudeAdapter(home=tmp_path)
    (ref,) = adapter.discover()
    assert (ref.harness, ref.session_id, ref.path, ref.cwd) == ("claude", SID, main, CWD)
    assert adapter.project(ref) == "my-repo"
    assert ClaudeAdapter.project(SessionRef(harness="claude", session_id=SID, path=main)) == "repo"


def _origin(entrypoint: str | None, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The records with Claude Code's `entrypoint` on its messages, the way it writes them."""
    if entrypoint is None:
        return records
    return [{**record, "entrypoint": entrypoint} if record.get("type") in ("user", "assistant") else record for record in records]


def _ids(adapter: ClaudeAdapter) -> set[str]:
    return {ref.session_id for ref in adapter.discover()}


SIDS = [f"1b864749-81a0-464c-8486-67a7995d34{n:02d}" for n in range(6)]


def test_discover_skips_chats_made_only_of_automated_sdk_runs(tmp_path: Path) -> None:
    # The prompt, project and file name say nothing; only the recorded origin decides.
    automated = _write(tmp_path, _origin("sdk-cli", _turn()), sid=SIDS[0])
    _write(tmp_path, _origin("cli", _turn()), sid=SIDS[1])
    _write(tmp_path, _origin("claude-desktop", _turn()), sid=SIDS[2])
    _write(tmp_path, _turn(), sid=SIDS[3])  # older Claude Code: no origin recorded
    _write(tmp_path, _origin("some-future-client", _turn()), sid=SIDS[4])
    # Interactive only past the first 50 lines, after a long automated stretch.
    long_run = [user(1, "Run the eval")] + [assistant(2, {"type": "text", "text": f"step {n}"}, msg_id=f"s{n}") for n in range(60)]
    _write(tmp_path, _origin("sdk-cli", long_run) + _origin("claude-desktop", [user(3, "Now let me look")]), sid=SIDS[5])
    adapter = ClaudeAdapter(home=tmp_path)
    assert _ids(adapter) == set(SIDS[1:])

    # More automated runs keep it hidden; a partial line is not read until it is complete.
    with automated.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({**user(8, "next eval"), "entrypoint": "sdk-cli"}) + "\n")
        handle.write(json.dumps({**user(9, "I'll take over"), "entrypoint": "cli"})[:40])
    assert SIDS[0] not in _ids(adapter)
    # Once someone continues it interactively, it shows up.
    with automated.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({**user(9, "I'll take over"), "entrypoint": "cli"})[40:] + "\n")
    assert SIDS[0] in _ids(adapter)
    hub = SessionHub([adapter], tail_bytes=None, rescan_seconds=0)
    assert f"claude:{SIDS[0]}" in {row["key"] for row in hub.inbox_dicts()}


def test_rewritten_transcript_is_judged_again(tmp_path: Path) -> None:
    path = _write(tmp_path, _origin("cli", _turn()), sid=SIDS[0])
    adapter = ClaudeAdapter(home=tmp_path)
    assert _ids(adapter) == {SIDS[0]}
    _write(tmp_path, _origin("sdk-cli", [user(1, "Eval")]), sid=SIDS[0])
    assert path.stat().st_size < 1000 and _ids(adapter) == set()


def _same_size(entrypoint: str, size: int | None = None) -> bytes:
    """A whole transcript of `entrypoint` messages, padded through its title to `size` bytes."""
    def text(title: str) -> bytes:
        records = _origin(entrypoint, _turn()[:-1]) + [{"type": "custom-title", "customTitle": title, "sessionId": SID}]
        return "".join(json.dumps(record) + "\n" for record in records).encode()
    return text("x" * (1 + (size - len(text("x")) if size else 0)))


@pytest.mark.parametrize("how", ["rewritten in place", "replaced by another file"])
def test_transcript_rewritten_to_the_same_size_is_judged_again(tmp_path: Path, how: str) -> None:
    automated = _same_size("sdk-cli", 4000)
    interactive = _same_size("cli", len(automated))
    assert len(interactive) == len(automated)
    path = _write(tmp_path, [])
    path.write_bytes(automated)
    adapter = ClaudeAdapter(home=tmp_path)
    assert _ids(adapter) == set()
    stamp = path.stat().st_mtime + 5
    if how == "rewritten in place":
        path.write_bytes(interactive)
    else:
        other = path.with_suffix(".tmp")
        other.write_bytes(interactive)
        os.replace(other, path)
    os.utime(path, (stamp, stamp))
    assert _ids(adapter) == {SID} == _ids(ClaudeAdapter(home=tmp_path))
    # And back: automated content of the same size is hidden again.
    path.write_bytes(automated)
    os.utime(path, (stamp + 5, stamp + 5))
    assert _ids(adapter) == set()


def test_handoff_resumes_the_session(tmp_path: Path) -> None:
    ref = SessionRef(harness="claude", session_id=SID, cwd=CWD)
    adapter = ClaudeAdapter(home=tmp_path)
    handoff = adapter.handoff(ref, None)
    # Claude Code finds sessions per project, so the command resumes from the chat's own folder.
    assert (handoff.resume_command, handoff.terminal_cwd) == (f"cd {CWD} && claude --resume {SID}", CWD)
    assert handoff.open_uri == "claude://code/new?folder=%2Fwork%2Fmy-repo"
    assert adapter.handoff(ref, "/work/my repo").resume_command == f"cd '/work/my repo' && claude --resume {SID}"
    assert adapter.handoff(ref, "/work/my repo").open_uri == "claude://code/new?folder=%2Fwork%2Fmy%20repo"
    assert adapter.handoff(SessionRef(harness="claude", session_id=SID), None).resume_command == f"claude --resume {SID}"
    assert adapter.handoff(SessionRef(harness="claude", session_id=SID), None).open_uri == "claude://code/new"


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

    assert SessionHub.for_codex_home(codex_home, scan_ttl=0).inbox_dicts() == []
    hub = SessionHub.for_codex_home(codex_home, scan_ttl=0, claude_home=claude)
    (row,) = hub.inbox_dicts()
    assert (row["harness"], row["title"], row["status"]) == ("claude", "Fix parser", "done")
    detail = hub.detail_dict(SessionKey.parse(f"claude:{SID}"))
    assert detail is not None and detail["handoff"]["resume_command"] == f"cd {CWD} && claude --resume {SID}"


def test_tool_call_without_a_result_is_reported_until_it_returns(tmp_path: Path) -> None:
    records = [user(1, "Deploy"), assistant(2, tool_use("t1", "Bash", command="make deploy\n--verbose"))]
    path = _write(tmp_path, records)
    ref = SessionRef(harness="claude", session_id=SID, path=path, cwd=CWD)
    cursor, folder = ClaudeCursor(ref), TurnFolder(ref)
    folder.fold_many(cursor.read_new())
    row = folder.inbox_fields()
    # Waiting on a tool is not waiting on the user: a long command looks the same.
    assert (row["status"], row["needs_you"], row["pending_tool"]) == ("working", False, "Bash: make deploy")

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(result(3, "t1", "ok")) + "\n")
        handle.write(json.dumps(assistant(4, tool_use("t2", "Write", file_path=f"{CWD}/notes/app.py", content="x"), msg_id="m2")) + "\n")
    folder.fold_many(cursor.read_new())
    assert folder.inbox_fields()["pending_tool"] == "Write: app.py"

    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(user(5, [{"type": "text", "text": "[Request interrupted by user]"}])) + "\n")
    folder.fold_many(cursor.read_new())
    assert (folder.status, folder.inbox_fields()["pending_tool"]) == ("interrupted", "")


def _hub(home: Path) -> SessionHub:
    """The app's own pipeline, so the folder uses what Claude Code's source can record."""
    return SessionHub([ClaudeAdapter(home=home)], tail_bytes=None, rescan_seconds=0)


def _bash(second: int, tool_id: str, command: str, output: str = "", *, failed: bool = False, **arguments: Any) -> list[dict[str, Any]]:
    return [assistant(second, tool_use(tool_id, "Bash", command=command, **arguments), msg_id=f"m{tool_id}"),
            result(second, tool_id, output, is_error=failed)]


def test_claude_check_result_is_judged_on_the_whole_command(tmp_path: Path) -> None:
    _write(tmp_path, [
        user(1, "Run the checks"),
        *_bash(2, "t1", "uv run pytest -q", "3 passed"),
        *_bash(3, "t2", "uv run ruff check .", "E501", failed=True),
        # The pipe's success is tail's: the tests may have failed.
        *_bash(4, "t3", "uv run mypy src 2>&1 | tail -3", "Found 2 errors"),
        # Starting a background run says nothing about how it ends.
        *_bash(5, "t4", "uv run pyright", "Command running in background with ID: b1", run_in_background=True),
    ])
    hub = _hub(tmp_path)
    folder = hub.folder(f"claude:{SID}")
    assert folder is not None
    (turn,) = folder.turns
    assert [(check.command, check.exit_code) for check in turn.checks] == [("uv run pytest -q", 0), ("uv run ruff check .", 1)]
    commands = {step.title: (step.detail, step.status) for step in folder.steps if step.kind == "command"}
    # Claude Code records only success or failure, so no exit number is shown.
    assert commands["uv run ruff check ."] == ("", "failed")
    assert commands["uv run mypy src 2>&1 | tail -3"] == ("check result not proven", "done")
    assert commands["uv run pyright"] == ("check result not proven", "done")
    detail = hub.detail_dict(f"claude:{SID}")
    assert detail is not None and detail["capabilities"] == {"exit_codes": False, "command_results": True, "live_activity": True}
    assert "full_command" not in json.dumps(detail)


def test_unproven_claude_check_keeps_an_earlier_failure_and_unchecked_edits(tmp_path: Path) -> None:
    _write(tmp_path, [
        user(1, "Fix the tests"),
        *_bash(2, "t1", "uv run pytest -q", "1 failed", failed=True),
        *_bash(3, "t2", "uv run pytest -q 2>&1 | tail -3", "1 failed"),
    ])
    edited = [
        user(1, "Change the parser"),
        assistant(2, tool_use("e1", "Edit", file_path=f"{CWD}/src/app.py", old_string="a", new_string="b"), msg_id="me1"),
        result(2, "e1"),
        *_bash(3, "t1", "uv run pytest -q | tail -3", "1 failed"),
    ]
    _write(tmp_path, edited, sid=SID_B)
    rows = {row["id"]: row for row in _hub(tmp_path).inbox_dicts()}
    assert rows[SID]["check_state"] == "failed"
    assert rows[SID_B]["check_state"] == "unchecked"


def test_silent_claude_turn_still_goes_quiet(tmp_path: Path) -> None:
    path = _write(tmp_path, [user(1, "Deploy"), assistant(2, tool_use("t1", "Bash", command="make deploy"))])
    hub = _hub(tmp_path)
    assert [row["quiet"] for row in hub.inbox_dicts()] == [False]
    stamp = time.time() - QUIET_SECONDS - 60
    os.utime(path, (stamp, stamp))
    (row,) = hub.inbox_dicts()
    assert (row["status"], row["quiet"], row["pending_tool"]) == ("working", True, "Bash: make deploy")


def test_decision_lines_in_the_final_answer_become_agent_decisions(tmp_path: Path) -> None:
    folder = _fold(_write(tmp_path, _turn(FINAL + "\n**Decision:** Patch or rewrite? -> patch (over rewrite). Smaller diff.")))
    (decision,) = folder.decisions
    assert (decision.source, decision.question, decision.options, decision.chosen, decision.reason, decision.turn) == (
        "agent", "Patch or rewrite?", ["patch", "rewrite"], "patch", "Smaller diff.", 1)
    assert ("decision", "Patch or rewrite?") in [(step.kind, step.title) for step in folder.steps]


# --- system-started continuations and queued messages ---------------------------------------------


def notification(second: int, origin: dict[str, Any] | None = None) -> dict[str, Any]:
    """Claude Code's user record when a background task ends, as it writes it."""
    content = "<task-notification><task-id>b1</task-id><status>completed</status></task-notification>"
    if origin is None:
        origin = {"kind": "task-notification", "producer": "session-task"}
    return user(second, content, **({"origin": origin} if origin else {}))


def queued(second: int, prompt: Any, source: str, kind: str = "human") -> dict[str, Any]:
    """A message the user typed while the agent worked, recorded only as an attachment."""
    attachment = {"type": "queued_command", "prompt": prompt, "commandMode": "prompt" if kind == "human" else kind,
                  "origin": {"kind": kind}, "source_uuid": source, "timestamp": _ts(second)}
    return _base(second, "attachment", attachment=attachment)


def _text(second: int, text: str, msg_id: str) -> dict[str, Any]:
    return assistant(second, {"type": "text", "text": text}, stop="end_turn", msg_id=msg_id)


def _shape(folder: TurnFolder) -> tuple[list[tuple[int, str, str, str]], list[tuple[str, str, str, str]]]:
    turns = [(turn.index, turn.status, turn.prompt, turn.outcome) for turn in folder.turns]
    return turns, [(step.kind, step.title, step.detail, step.status) for step in folder.steps]


def _incremental(tmp_path: Path, records: list[dict[str, Any]]) -> TurnFolder:
    """The same records appended one at a time, read after each."""
    path = _write(tmp_path, [], sid=SID_B)
    ref = SessionRef(harness="claude", session_id=SID_B, path=path, cwd=CWD)
    folder, cursor = TurnFolder(ref, command_results=True), ClaudeCursor(ref)
    for record in records:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record) + "\n")
        folder.fold_many(cursor.read_new())
    return folder


def _both(tmp_path: Path, records: list[dict[str, Any]]) -> TurnFolder:
    path = _write(tmp_path, records)
    ref = SessionRef(harness="claude", session_id=SID, path=path, cwd=CWD)
    full = TurnFolder(ref, command_results=True)
    full.fold_many(ClaudeCursor(ref).read_new())
    assert _shape(_incremental(tmp_path, records)) == _shape(full)
    return full


def test_task_notification_after_a_finished_turn_starts_a_new_one(tmp_path: Path) -> None:
    records = [user(1, "Start the build in the background"), _text(2, "Started.", "m1"), notification(3)]
    folder = _both(tmp_path, records)
    # Work resumed by the system: no longer done, and no prompt is put in the user's mouth.
    assert [(turn.status, turn.prompt) for turn in folder.turns] == [("done", "Start the build in the background"), ("working", "")]
    assert folder.status == "working"
    assert [step.title for step in folder.steps if step.kind == "user"] == ["You"]
    assert "Turn 2 started by a background task" in [step.title for step in folder.steps]

    records += [*_bash(4, "t1", "uv run pytest -q", "3 passed"), notification(5)]
    folder = _both(tmp_path, records)
    assert (len(folder.turns), folder.status, folder.turns[-1].checks[0].command) == (2, "working", "uv run pytest -q")
    records.append(_text(6, "Outcome: Build and tests pass.\nNext step: none", "m9"))
    folder = _both(tmp_path, records)
    assert [(turn.status, turn.outcome) for turn in folder.turns] == [("done", "Started."), ("done", "Build and tests pass.")]


def test_task_notification_inside_an_open_turn_changes_nothing(tmp_path: Path) -> None:
    records = [
        user(1, "Run the slow suite"),
        assistant(2, tool_use("t1", "Bash", command="make slow", run_in_background=True), msg_id="m1"),
        result(3, "t1", "Command running in background with ID: b1"),
        assistant(4, tool_use("t2", "Bash", command="uv run pytest -q"), msg_id="m2"),
        notification(5),
        queued(5, "late notice", "q0", kind="task-notification"),
        result(6, "t2", "3 passed"),
        _text(7, "Outcome: Suite passes.\nNext step: none", "m3"),
    ]
    folder = _both(tmp_path, records)
    (turn,) = folder.turns
    # The call still running when the notification came keeps its result.
    assert (turn.status, [check.command for check in turn.checks]) == ("done", ["uv run pytest -q"])
    assert not [step for step in folder.steps if step.status == "failed" or step.kind == "user" and step.title != "You"]


def test_notification_text_without_its_origin_is_not_a_continuation(tmp_path: Path) -> None:
    folder = _both(tmp_path, [user(1, "Go"), _text(2, "Done.", "m1"), notification(3, origin={})])
    assert [turn.status for turn in folder.turns] == ["done"]


def test_queued_message_joins_the_running_turn(tmp_path: Path) -> None:
    image = {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "AAAA"}}
    records = [
        user(1, "Refactor the parser"),
        assistant(2, tool_use("t1", "Bash", command="uv run pytest -q"), msg_id="m1"),
        queued(3, "commit all when green", "q1"),
        queued(3, "commit all when green", "q1"),  # the same message recorded twice
        queued(4, "commit all when green", "q2"),  # typed again on purpose
        queued(4, [image, {"type": "text", "text": "match this layout"}], "q3"),
        queued(4, [image, image], "q4"),
        result(5, "t1", "3 passed"),
        _text(6, "Outcome: Refactored and committed.\nNext step: none", "m2"),
    ]
    folder = _both(tmp_path, records)
    (turn,) = folder.turns
    assert (turn.status, turn.prompt, [check.command for check in turn.checks]) == ("done", "Refactor the parser", ["uv run pytest -q"])
    said = [step.detail for step in folder.steps if step.kind == "user"]
    assert said == ["Refactor the parser", "commit all when green", "commit all when green", "[image] match this layout", "[2 images]"]


# --- Claude Code's own messages, and how the next step is known ------------------------------------

LOGIN = "Login expired · Please run /login"


def synthetic(second: int, text: str, **flags: Any) -> dict[str, Any]:
    """A message Claude Code writes itself, not the model: an API error, or a note like "No response requested."."""
    record = assistant(second, {"type": "text", "text": text}, stop="stop_sequence", msg_id=f"s{second}",
                       usage={"input_tokens": 0, "output_tokens": 0})
    record["message"]["model"] = "<synthetic>"
    return {**record, **flags}


def _row(folder: TurnFolder) -> tuple[str, str, str, bool, str]:
    row = folder.inbox_fields()
    return row["status"], row["outcome"], row["next_kind"], row["needs_you"], row["next_basis"]


def test_api_error_ends_the_turn_as_a_failure_not_an_answer(tmp_path: Path) -> None:
    folder = _both(tmp_path, [user(1, "Fix the bug"), synthetic(2, LOGIN, isApiErrorMessage=True, error="authentication_failed")])
    # The diagnostic is the stop's reason; it is never read as a handoff that says "run /login".
    assert _row(folder) == ("interrupted", "", "unknown", False, "")
    assert ("turn", "Turn 1 stopped", f"authentication_failed: {LOGIN}", "failed") in _shape(folder)[1]
    assert not [step for step in folder.steps if step.kind in ("answer", "message")]
    assert folder.model == ""


def _flagged(model: str | None, text: str) -> dict[str, Any]:
    record = synthetic(2, text, isApiErrorMessage=True, error="authentication_failed")
    if model is None:
        del record["message"]["model"]
    else:
        record["message"]["model"] = model
    if not text:
        record["message"]["content"] = []
    return record


@pytest.mark.parametrize(("model", "text", "reason"), [
    pytest.param(None, LOGIN, f"authentication_failed: {LOGIN}", id="no model"),
    pytest.param("claude-opus-5-5", LOGIN, f"authentication_failed: {LOGIN}", id="a real model"),
    pytest.param("<synthetic>", "", "authentication_failed", id="no text"),
])
def test_api_error_flag_alone_decides(tmp_path: Path, model: str | None, text: str, reason: str) -> None:
    folder = _both(tmp_path, [user(1, "Fix the bug"), _flagged(model, text)])
    assert _row(folder) == ("interrupted", "", "unknown", False, "")
    assert ("turn", "Turn 1 stopped", reason, "failed") in _shape(folder)[1]
    assert not [step for step in folder.steps if step.kind in ("answer", "message")]


def test_claude_codes_own_note_is_neither_a_failure_nor_an_answer(tmp_path: Path) -> None:
    folder = _both(tmp_path, [user(1, "Fix the bug"), synthetic(2, "No response requested.", isApiErrorMessage=False)])
    assert _row(folder) == ("done", "", "unknown", False, "")
    assert not [step for step in folder.steps if step.kind in ("answer", "message") or step.status == "failed"]


def test_synthetic_message_without_its_error_flag_stays_uncertain(tmp_path: Path) -> None:
    folder = _both(tmp_path, [user(1, "Fix the bug"), synthetic(2, LOGIN)])
    # Not judged a failure by its words, nor an answer whose wording asks to run something.
    assert _row(folder) == ("unknown", "", "unknown", False, "")
    assert not [step for step in folder.steps if step.kind in ("answer", "message") or step.status == "failed"]


@pytest.mark.parametrize(("answer", "expected"), [
    pytest.param("**Outcome:** Fixed.\n**Next step:** none", ("done", "Fixed.", "none", False, "handoff"), id="explicit none"),
    pytest.param("**Outcome:** Fixed.\n**Next step:** review: the diff", ("done", "Fixed.", "review", True, "handoff"), id="handoff request"),
    pytest.param("Fixed the parser.\n\nReady to move on to the code fix, or anything else?",
                 ("done", "Fixed the parser.", "answer", True, "inferred"), id="request read from prose"),
    pytest.param("Fixed the parser.", ("done", "Fixed the parser.", "unknown", False, "no_handoff"), id="answer without a handoff"),
    pytest.param("**Outcome:** Fixed.", ("done", "Fixed.", "unknown", False, "no_next_step"), id="outcome without a next step"),
])
def test_next_step_says_whether_the_handoff_or_a_guess_named_it(tmp_path: Path, answer: str, expected: tuple[Any, ...]) -> None:
    folder = _both(tmp_path, [user(1, "Fix the bug"), _text(2, answer, "m1")])
    assert _row(folder) == expected
    assert folder.to_dict()["next_basis"] == expected[-1]


def test_source_question_and_running_turn_are_not_judged_on_wording(tmp_path: Path) -> None:
    ask = tool_use("q1", "AskUserQuestion", questions=[{"question": "Ship now?", "options": [{"label": "Yes"}, {"label": "No"}]}])
    folder = _both(tmp_path, [user(1, "Release"), assistant(2, ask, msg_id="m1")])
    assert (folder.inbox_fields()["needs_you"], folder.inbox_fields()["next_basis"]) == (True, "source")
    working = _both(tmp_path, [user(1, "Release"), assistant(2, {"type": "text", "text": "Checking the tag first."}, stop="tool_use", msg_id="m1")])
    assert _row(working) == ("working", "", "unknown", False, "")


PROMPT = "commit when green"
RESULT = {"type": "tool_result", "tool_use_id": "t1", "content": "3 passed", "is_error": False}


@pytest.mark.parametrize(("middle", "said"), [
    pytest.param([queued(3, PROMPT, "q1"), user(4, PROMPT, uuid="q1")], ["Refactor", PROMPT], id="queued then its user record"),
    pytest.param([queued(3, PROMPT, "q1"), queued(4, PROMPT, "q1")], ["Refactor", PROMPT], id="queued twice"),
    pytest.param([queued(3, PROMPT, "q1"), user(4, [RESULT, {"type": "text", "text": PROMPT}], uuid="q1")], ["Refactor", PROMPT],
                 id="user record repeating the prompt beside a tool result"),
])
def test_message_recorded_twice_counts_once_and_the_running_call_keeps_its_result(
        tmp_path: Path, middle: list[dict[str, Any]], said: list[str]) -> None:
    records = [user(1, "Refactor"), assistant(2, tool_use("t1", "Bash", command="pytest"), msg_id="m1"), *middle,
               result(5, "t1", "3 passed"), _text(6, "Outcome: Committed.\nNext step: none", "m2")]
    folder = _both(tmp_path, records)
    (turn,) = folder.turns
    assert (turn.status, [(check.command, check.exit_code) for check in turn.checks]) == ("done", [("pytest", 0)])
    assert [step.detail for step in folder.steps if step.kind == "user"] == said
    assert not [step for step in folder.steps if step.status == "failed"]


def test_prompt_recorded_again_as_a_queued_message_counts_once(tmp_path: Path) -> None:
    records = [user(1, PROMPT, uuid="q1"), assistant(2, tool_use("t1", "Bash", command="pytest"), msg_id="m1"),
               queued(3, PROMPT, "q1"), result(4, "t1", "3 passed"), _text(5, "Outcome: Committed.\nNext step: none", "m2")]
    folder = _both(tmp_path, records)
    (turn,) = folder.turns
    assert (turn.status, [check.command for check in turn.checks]) == ("done", ["pytest"])
    assert [step.detail for step in folder.steps if step.kind == "user"] == [PROMPT]


def test_same_words_under_different_identities_stay_two_messages(tmp_path: Path) -> None:
    records = [user(1, "Refactor"), assistant(2, tool_use("t1", "Bash", command="pytest"), msg_id="m1"),
               queued(3, PROMPT, "q1"), user(4, PROMPT, uuid="q2"), _text(5, "Outcome: Committed.\nNext step: none", "m2")]
    folder = _both(tmp_path, records)
    assert [step.detail for step in folder.steps if step.kind == "user"] == ["Refactor", PROMPT, PROMPT]
    assert [(turn.status, turn.prompt) for turn in folder.turns] == [("interrupted", "Refactor"), ("done", PROMPT)]
