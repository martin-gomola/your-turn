from __future__ import annotations

import json
import os
import threading
import time
from collections import deque
from pathlib import Path

import pytest
from conftest import (
    OTHER,
    RECORDS,
    Parser,
    SUBAGENT,
    THREAD,
    append,
    command,
    edit,
    event,
    item,
    meta,
    write_rollout,
)

from yourturn.engine import RolloutTail, SessionHub
from yourturn.heuristics import parse_answer, parse_recap


def test_folds_a_turn_into_a_summary_steps_and_decisions(codex_home: Path) -> None:
    state = SessionHub.for_codex_home(codex_home).state(THREAD)

    assert state is not None
    assert (state.title, state.cwd, state.status, state.subagent) == ("Fix login", "/w/repo", "waiting", False)
    assert (state.context_used, state.context_window) == (250, 1000)
    (turn,) = state.turns
    assert (turn.index, turn.status, turn.prompt) == (1, "waiting", "Fix the login bug")
    assert (turn.outcome, turn.formatted) == ("Need input. More text.", False)
    assert (turn.next_kind, turn.next_text) == ("answer", "Ship now?")
    assert turn.files == ["/w/repo/auth.py"]
    assert [(c.command, c.exit_code) for c in turn.checks] == [("uv run pytest -q", 1)]
    assert turn.edited_after_check is True
    kinds = [step.kind for step in state.steps]
    assert kinds == ["turn", "user", "thinking", "command", "edit", "decision", "answer", "question", "turn"]
    agent, asked = state.decisions
    assert (agent.source, agent.chosen, agent.reason) == ("agent", "Handler", "Smaller change")
    assert (asked.source, asked.question, asked.chosen) == ("asked", "Ship now?", None)


def test_later_check_clears_the_stale_flag_and_formatted_answer_sets_next_step(codex_home: Path) -> None:
    sessions = SessionHub.for_codex_home(codex_home)
    path = sessions.find(THREAD)
    assert path is not None and sessions.state(THREAD) is not None
    reply = '<send_user_message_question_reply>\n[{"question":"Ship now?","answer":"Yes"}]\n</send_user_message_question_reply>'
    append(
        path,
        event("2026-10-27T10:04:00Z", {"type": "task_started"}),
        item("2026-10-27T10:04:01Z", {"type": "UserMessage", "content": [{"text": reply}]}),
        edit("2026-10-27T10:04:02Z", "/w/repo/auth.py"),
        command("2026-10-27T10:04:03Z", "uv run pytest -q", 0),
        item("2026-10-27T10:04:04Z", {"type": "AgentMessage", "phase": "final_answer", "content": [{"text":
             "**Outcome:** Login works again.\n**Next step:** review: the session timeout change\n\nDetails…"}]}),
        event("2026-10-27T10:04:05Z", {"type": "task_complete"}),
    )

    state = sessions.state(THREAD)
    assert state is not None
    assert state.decisions[-1].chosen == "Yes"
    turn = state.turns[-1]
    assert (turn.index, turn.status, turn.prompt) == (2, "done", "Answered: Yes")
    assert (turn.outcome, turn.next_kind, turn.next_text, turn.formatted) == ("Login works again.", "review", "the session timeout change", True)
    assert (turn.edited_after_check, turn.checks[-1].exit_code) == (False, 0)
    assert state.status == "done"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Outcome: Done.\nNext step: none", ("Done.", "none", "", True)),
        ("## Outcome: Shipped\n- **Next step:** run: make deploy", ("Shipped", "run", "make deploy", True)),
        ("**Result:** Found it\n**Next step:** Check the logs tomorrow", ("Found it", "do", "Check the logs tomorrow", True)),
        ("Fixed the bug. Also refactored.\n\nMore.", ("Fixed the bug. Also refactored.", "unknown", "", False)),
        ("Stopped. No source was inspected and no ingestion artifacts were written.",
         ("Stopped. No source was inspected and no ingestion artifacts were written.", "unknown", "", False)),
        ("## Decision\n\n**Keep the local CLI.** No queue is needed.\n\nRisk: memory.",
         ("Keep the local CLI. No queue is needed.", "unknown", "", False)),
        ("Please provide:\n\n1. The source location.\n2. A license reference.\n\nOnce I have those, I'll continue.",
         ("1. The source location. 2. A license reference.", "answer", "Please provide: 1. The source location. 2. A license reference.", False)),
        ("Added the config.\n\nShould I also update staging?", ("Added the config.", "answer", "Should I also update staging?", False)),
        ("Fixed the import.\n\nRun `make test` to confirm.", ("Fixed the import.", "run", "Run make test to confirm.", False)),
        ("Added the migration.\n\nTo apply it, please run `make migrate`.",
         ("Added the migration.", "run", "To apply it, please run make migrate.", False)),
        ("Updated the docs.\n\nNext steps:\n\n- Run `uv sync`\n- Restart the server",
         ("Updated the docs.", "run", "Next steps: Run uv sync Restart the server", False)),
        ("Drafted the fix.\n\nPlease review the diff in auth.py.", ("Drafted the fix.", "review", "Please review the diff in auth.py.", False)),
        ("Wrote the report.\n\nTake a look at report.md before I send it.",
         ("Wrote the report.", "review", "Take a look at report.md before I send it.", False)),
        ("Found two options.\n\nLet me know which one you prefer.",
         ("Found two options.", "answer", "Let me know which one you prefer.", False)),
        ("Tests pass.\n\nWould you like me to open a PR as well.",
         ("Tests pass.", "answer", "Would you like me to open a PR as well.", False)),
        ("Fixed the typo. I ran pytest and all tests pass.", ("Fixed the typo. I ran pytest and all tests pass.", "unknown", "", False)),
        ("Cached the lookup.\n\nRun time dropped from 4s to 1s, and the tests were run twice.",
         ("Cached the lookup.", "unknown", "", False)),
        ("Checked the logs.\n\nLet me take a look at the config next; I reviewed the diff already.",
         ("Checked the logs.", "unknown", "", False)),
        ("Renamed the flag.\n\nI should note the old name still works.", ("Renamed the flag.", "unknown", "", False)),
        ("Fixed the login bug.\n\nLet me know if you have any questions.", ("Fixed the login bug.", "unknown", "", False)),
        ("Raised the limit.\n\nOtherwise you'll run into the same timeout on large inputs.", ("Raised the limit.", "unknown", "", False)),
        ("Benchmarked it.\n\nThe first run failed; run two passed. The benchmark: run 2 took 5s.", ("Benchmarked it.", "unknown", "", False)),
        ("Scheduled it.\n\nThe pipeline will run nightly, then run cleanup.", ("Scheduled it.", "unknown", "", False)),
        ("Set up previews.\n\nOnce merged, review apps deploy automatically.", ("Set up previews.", "unknown", "", False)),
        ("Fixed it.\n\nRun: `make test`", ("Fixed it.", "run", "Run: make test", False)),
        ("Wrote the deploy script.\n\n```sh\nif ok; then run ./deploy; fi\n```", ("Wrote the deploy script.", "unknown", "", False)),
    ],
)
def test_parse_answer(text: str, expected: tuple[str, str, str, bool]) -> None:
    assert parse_answer(text) == expected


def test_parse_answer_is_linear_on_blank_lines() -> None:
    started = time.perf_counter()
    parse_answer("Done." + "\n" * 50_000 + "Outcome: still found")
    parse_recap("\n" * 50_000)
    assert time.perf_counter() - started < 0.5


def test_parse_recap() -> None:
    text = "**Outcome:** Typo fixed.\n**Next step:** none\n**Recap:** Login fix shipped; only polish is left.\n\nMore."
    assert parse_answer(text) == ("Typo fixed.", "none", "", True)
    assert parse_recap(text) == "Login fix shipped; only polish is left."
    assert parse_recap("**Outcome:** Done.") == ""


def test_inbox_skips_subagents_and_reads_only_the_tail(codex_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_rollout(codex_home, SUBAGENT, [meta(SUBAGENT, {"subagent": {"other": "guardian"}})], day="2026/10/28")
    write_rollout(codex_home, OTHER, [meta(OTHER), event("2026-10-28T09:00:00Z", {"type": "task_started"})], day="2026/10/28")
    sessions = SessionHub.for_codex_home(codex_home, scan_ttl=0)

    inbox = {entry["id"]: entry for entry in sessions.inbox_dicts()}
    assert set(inbox) == {THREAD, OTHER}
    assert (inbox[THREAD]["status"], inbox[THREAD]["question"], inbox[THREAD]["title"]) == ("waiting", "Ship now?", "Fix login")
    assert inbox[THREAD]["options"] == ["Yes", "No"]
    assert inbox[OTHER]["status"] == "working"

    monkeypatch.setattr(sessions, "tail_bytes", 200)
    path = sessions.find(THREAD)
    assert path is not None
    append(path, event("2026-10-27T10:05:00Z", {"type": "task_started"}))
    assert {entry["id"]: entry for entry in sessions.inbox_dicts()}[THREAD]["status"] == "working"
    assert {entry["id"]: entry for entry in sessions.inbox_dicts()}[THREAD]["cwd"] == "/w/repo"


def test_inbox_uses_one_history_window_for_all_statuses(codex_home: Path) -> None:
    done = [meta(OTHER), event("2026-10-27T10:00:00Z", {"type": "task_started"}), event("2026-10-27T10:00:01Z", {"type": "task_complete"})]
    ids = [f"0d3e1000-0000-7000-8000-00000000001{i}" for i in range(4)]
    paths = {thread: write_rollout(codex_home, thread, [meta(thread), *done[1:]]) for thread in ids}
    stale_waiting = write_rollout(codex_home, "0d3e1000-0000-7000-8000-000000000020", RECORDS)
    now = time.time()
    for age, path in [(1, paths[ids[0]]), (2, paths[ids[1]]), (3 * 86400, codex_home / "sessions/2026/10/27" / f"rollout-2026-10-27T11-03-04-{THREAD}.jsonl"),
                      (4 * 86400, paths[ids[2]]), (5 * 86400, paths[ids[3]]), (20 * 86400, stale_waiting)]:
        os.utime(path, (now - age, now - age))

    inbox = [entry["id"] for entry in SessionHub.for_codex_home(codex_home, scan_ttl=0).inbox_dicts(history_days=4)]
    assert inbox == [ids[0], ids[1], THREAD]
    assert len(SessionHub.for_codex_home(codex_home).inbox_dicts(history_days=14)) == 5
    assert len(SessionHub.for_codex_home(codex_home).inbox_dicts(history_days=30)) == 6


def test_attention_identity_survives_usage_updates_and_tail_reads(codex_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sessions = SessionHub.for_codex_home(codex_home, scan_ttl=0)
    state = sessions.state(THREAD)
    assert state is not None
    key = state.attention_key
    assert len(key) == 64
    path = sessions.find(THREAD)
    assert path is not None
    append(path, event("2026-10-27T10:05:00Z", {"type": "token_count", "info": {"total_token_usage": {"total_tokens": 999}}}))
    monkeypatch.setattr(sessions, "tail_bytes", 2000)
    assert sessions.inbox_dicts()[0]["attention_key"] == key
    assert sessions.state(THREAD).attention_key == key


def test_new_request_gets_new_identity_even_with_identical_text(codex_home: Path) -> None:
    sessions = SessionHub.for_codex_home(codex_home, scan_ttl=0)
    old = sessions.inbox_dicts()[0]["attention_key"]
    path = sessions.find(THREAD)
    assert path is not None
    append(path, event("2026-10-27T10:06:00Z", {"type": "task_started"}))
    assert sessions.inbox_dicts()[0]["attention_key"] == ""
    append(path,
           item("2026-10-27T10:06:01Z", {"type": "AgentMessage", "questions": [{"title": "Ship now?", "options": ["Yes", "No"]}]}),
           event("2026-10-27T10:06:02Z", {"type": "task_complete"}))
    new = sessions.inbox_dicts()[0]["attention_key"]
    assert new and new != old
    assert sessions.state(THREAD).attention_key == new


def test_final_action_identity_tracks_full_request_not_clipped_preview() -> None:
    parser = Parser(THREAD)
    prefix = "Outcome: Done\nNext step: review: " + "a" * 400
    parser.feed(item("2026-10-27T10:06:01Z", {"type": "AgentMessage", "phase": "final_answer", "content": [{"text": prefix + "one"}]}))
    old = parser.state.attention_key
    parser.feed(item("2026-10-27T10:06:01Z", {"type": "AgentMessage", "phase": "final_answer", "content": [{"text": prefix + "two"}]}))
    assert old and parser.state.attention_key != old
    parser.feed(item("2026-10-27T10:06:02Z", {"type": "AgentMessage", "phase": "final_answer", "content": [{"text": "Outcome: Done\nNext step: none"}]}))
    assert parser.state.attention_key == ""


def test_reports_latest_usage_snapshot_without_double_counting(codex_home: Path) -> None:
    sessions = SessionHub.for_codex_home(codex_home)
    path = sessions.find(THREAD)
    assert path is not None
    append(
        path,
        {"type": "turn_context", "payload": {"model": "fixture-model", "effort": "high"}},
        event("2026-10-27T10:06:00Z", {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": 120, "cached_input_tokens": 80, "output_tokens": 40, "reasoning_output_tokens": 10, "total_tokens": 160},
            "last_token_usage": {"total_tokens": 90}, "model_context_window": 1000,
        }}),
        event("2026-10-27T10:07:00Z", {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": 200, "cached_input_tokens": 150, "cache_write_input_tokens": 0, "output_tokens": 60, "reasoning_output_tokens": 20, "total_tokens": 260},
            "last_token_usage": {"total_tokens": 0}, "model_context_window": 1000,
        }}),
    )
    state = sessions.state(THREAD)
    assert state is not None
    assert (state.model, state.reasoning_effort) == ("fixture-model", "high")
    assert state.token_usage == {"input_tokens": 200, "cached_input_tokens": 150, "cache_write_input_tokens": 0, "output_tokens": 60, "reasoning_output_tokens": 20, "total_tokens": 260}
    assert state.token_usage_at == "2026-10-27T10:07:00Z"
    assert state.context_used == 0 and state.last_token_usage == {"total_tokens": 0}


def test_usage_and_session_metadata_ignore_malformed_values() -> None:
    parser = Parser(THREAD)
    parser.feed({"type": "session_meta", "payload": {"cwd": "/w/repo", "model_provider": "fixture-provider", "cli_version": "1.2.3", "git": {"branch": "feature/telemetry"}}})
    for info in (None, [], {"total_token_usage": [1], "last_token_usage": "invalid", "model_context_window": "unknown"}):
        parser.feed(event("2026-10-27T10:08:00Z", {"type": "token_count", "info": info}))
    assert parser.state.token_usage == {} and parser.state.last_token_usage == {}
    parser.feed(event("2026-10-27T10:09:00Z", {"type": "token_count", "info": {
        "total_token_usage": {"input_tokens": -1, "cached_input_tokens": True, "output_tokens": "12", "total_tokens": 0, "unknown_field": 42},
        "last_token_usage": {"total_tokens": False}, "model_context_window": -1,
    }}))
    assert parser.state.token_usage == {"total_tokens": 0}
    assert parser.state.last_token_usage == {} and parser.state.context_window == 0
    assert (parser.state.model_provider, parser.state.cli_version, parser.state.git_branch) == ("fixture-provider", "1.2.3", "feature/telemetry")
    parser.feed({"type": "turn_context", "payload": {"model": "first-model", "effort": "high"}})
    parser.feed({"type": "turn_context", "payload": {"model": "second-model"}})
    assert (parser.state.model, parser.state.reasoning_effort) == ("second-model", "")


def test_malformed_records_are_skipped_without_losing_later_lines(codex_home: Path) -> None:
    sessions = SessionHub.for_codex_home(codex_home)
    path = sessions.find(THREAD)
    assert path is not None and sessions.state(THREAD) is not None
    reply = '<send_user_message_question_reply>["yes"]</send_user_message_question_reply>'
    append(
        path,
        event("2026-10-27T10:10:00Z", {"type": "task_started"}),
        item("2026-10-27T10:10:01Z", {"type": "AgentMessage", "content": [], "questions": ["Pick one?"]}),
        item("2026-10-27T10:10:02Z", {"type": "FileChange", "changes": [{"path": "a.py"}]}),
        item("2026-10-27T10:10:03Z", {"type": "UserMessage", "content": [{"text": reply}]}),
        event("2026-10-27T10:10:04Z", {"type": "task_complete", "duration_ms": "12"}),
    )
    state = sessions.state(THREAD)
    assert state is not None
    assert (state.status, state.turns[-1].index, state.turns[-1].files) == ("done", 2, [])


def test_concurrent_reads_feed_each_record_once(codex_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = write_rollout(codex_home, OTHER, [meta(OTHER)])
    sessions = SessionHub.for_codex_home(codex_home)
    assert sessions.state(OTHER) is not None
    append(path, *[command("2026-10-27T10:04:00Z", "ls", 0) for _ in range(20000)])
    original_read, active, overlaps = RolloutTail.read, [], []

    def tracked_read(self: RolloutTail) -> object:
        active.append(self)
        overlaps.append(len(active))
        time.sleep(0.05)
        try:
            return original_read(self)
        finally:
            active.remove(self)

    monkeypatch.setattr(RolloutTail, "read", tracked_read)
    threads = [threading.Thread(target=sessions.state, args=(OTHER,)) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    state = sessions.state(OTHER)
    assert state is not None and state.version == 20001
    assert max(overlaps) == 1


def test_superseded_turn_is_closed_as_interrupted() -> None:
    parser = Parser(THREAD)
    parser.feed(event("2026-10-27T10:11:00Z", {"type": "task_started"}))
    parser.feed(event("2026-10-27T10:12:00Z", {"type": "task_started"}))
    first, second = parser.state.turns
    assert (first.status, first.ended_at) == ("interrupted", "2026-10-27T10:12:00Z")
    assert (second.status, parser.state.status) == ("working", "working")


def test_rewritten_shorter_file_is_reparsed_from_the_start(codex_home: Path) -> None:
    sessions = SessionHub.for_codex_home(codex_home)
    path = sessions.find(THREAD)
    assert path is not None and sessions.state(THREAD) is not None
    path.write_text(json.dumps(meta(THREAD)) + "\n" + json.dumps(event("2026-10-27T11:00:00Z", {"type": "task_started"})) + "\n")
    state = sessions.state(THREAD)
    assert state is not None
    assert (state.status, len(state.turns), state.decisions) == ("working", 1, [])


def test_tail_skips_the_partial_first_line_and_waits_for_a_complete_last_line(tmp_path: Path) -> None:
    path = tmp_path / f"rollout-x-{THREAD}.jsonl"
    started = json.dumps(event("2026-10-27T10:00:00Z", {"type": "task_started"})) + "\n"
    complete = json.dumps(event("2026-10-27T10:00:01Z", {"type": "task_complete"})) + "\n"
    path.write_text(json.dumps(meta(THREAD)) + "\n" + started + complete[:20])
    tail = RolloutTail(path, THREAD, start=len(json.dumps(meta(THREAD))) + 5)
    state = tail.read()
    assert (state.cwd, state.turns, state.status) == ("/w/repo", deque(), "idle")
    path.write_text(path.read_text() + complete[20:])
    assert tail.read().status == "done"


def test_aborted_turn_is_interrupted() -> None:
    parser = Parser(THREAD)
    parser.feed(event("2026-10-27T10:00:00Z", {"type": "task_started"}))
    parser.feed(event("2026-10-27T10:00:05Z", {"type": "turn_aborted", "reason": "user"}))
    (turn,) = parser.state.turns
    assert (turn.status, turn.ended_at, parser.state.status) == ("interrupted", "2026-10-27T10:00:05Z", "interrupted")
    assert (parser.state.steps[-1].title, parser.state.steps[-1].status) == ("Turn 1 stopped", "failed")


def test_rejects_non_thread_ids(codex_home: Path) -> None:
    sessions = SessionHub.for_codex_home(codex_home)
    assert sessions.find("../../etc/passwd") is None
    assert sessions.find("*") is None


def test_history_expiry_updates_inbox_and_stream_marker(codex_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sessions = SessionHub.for_codex_home(codex_home, scan_ttl=0)
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now)
    before = sessions.inbox_fingerprint(1)
    assert sessions.inbox_dicts(1)
    monkeypatch.setattr(time, "time", lambda: now + 2 * 86400)
    assert sessions.inbox_dicts(1) == []
    assert sessions.inbox_fingerprint(1) != before


def test_inbox_has_no_hidden_thirty_chat_cap(codex_home: Path) -> None:
    for number in range(31):
        thread = f"0d3e9999-0000-7000-8000-{number:012x}"
        write_rollout(codex_home, thread, [meta(thread), event("2026-10-27T10:00:00Z", {"type": "task_started"})])
    assert len(SessionHub.for_codex_home(codex_home).inbox_dicts()) == 32
