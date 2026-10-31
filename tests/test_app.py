from __future__ import annotations

import io
import json
import re
import time
from importlib.resources import files
from pathlib import Path

import pytest
from conftest import OTHER, SUBAGENT, THREAD, command, edit, event, item, meta, write_rollout
from fastapi.testclient import TestClient

from yourturn import rollout
from yourturn.app import create_app
from yourturn.mcp import serve
from yourturn.rollout import QUIET_SECONDS, Sessions


def client(codex_home: Path) -> TestClient:
    return TestClient(create_app(codex_home), base_url="http://127.0.0.1")


def test_inbox_lists_chats_without_subagents_or_exec_runs(codex_home: Path) -> None:
    write_rollout(codex_home, SUBAGENT, [meta(SUBAGENT, {"subagent": {"thread_spawn": {}}})])
    # `codex exec` runs are scripted, headless sessions with no chat in Codex.
    write_rollout(codex_home, OTHER, [meta(OTHER, "exec"), event("2026-10-27T10:00:00Z", {"type": "task_started"})])
    inbox = client(codex_home).get("/api/inbox").json()

    assert [(entry["id"], entry["status"], entry["title"]) for entry in inbox] == [(THREAD, "waiting", "Fix login")]


def test_needs_you_is_computed_server_side(codex_home: Path) -> None:
    done = [event("2026-10-27T10:00:00Z", {"type": "task_started"})]
    answer = {"type": "AgentMessage", "phase": "final_answer"}
    write_rollout(codex_home, OTHER, [meta(OTHER), *done,
                  item("2026-10-27T10:00:01Z", {**answer, "content": [{"text": "Outcome: Ok\nNext step: review: the diff"}]}),
                  event("2026-10-27T10:00:02Z", {"type": "task_complete"})])
    write_rollout(codex_home, SUBAGENT, [meta(SUBAGENT), *done,
                  item("2026-10-27T10:00:01Z", {**answer, "content": [{"text": "Outcome: Ok\nNext step: none"}]}),
                  event("2026-10-27T10:00:02Z", {"type": "task_complete"})])
    app = client(codex_home)

    inbox = {entry["id"]: entry["needs_you"] for entry in app.get("/api/inbox").json()}
    assert inbox == {THREAD: True, OTHER: True, SUBAGENT: False}
    assert app.get(f"/api/threads/{THREAD}").json()["needs_you"] is True
    assert app.get(f"/api/threads/{SUBAGENT}").json()["needs_you"] is False


def test_working_chat_turns_quiet_when_its_file_stops_changing(codex_home: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_rollout(codex_home, OTHER, [meta(OTHER), event("2026-10-27T10:00:00Z", {"type": "task_started"})])
    sessions = Sessions(codex_home)
    assert {entry["id"]: entry["quiet"] for entry in sessions.inbox()} == {THREAD: False, OTHER: False}
    before = sessions.inbox_fingerprint()

    later = time.time() + QUIET_SECONDS + 1
    monkeypatch.setattr(rollout.time, "time", lambda: later)
    assert sessions.inbox_fingerprint() != before, "turning quiet must reach the live inbox without a file write"
    assert {entry["id"]: entry["quiet"] for entry in sessions.inbox()} == {THREAD: False, OTHER: True}, "a finished chat is never quiet"
    assert sessions.snapshot(OTHER)["quiet"] is True
    assert sessions.snapshot(THREAD)["quiet"] is False


def test_inbox_reports_failed_and_unchecked_turns(codex_home: Path) -> None:
    start = event("2026-10-27T10:00:00Z", {"type": "task_started"})
    end = event("2026-10-27T10:00:09Z", {"type": "task_complete"})
    write_rollout(codex_home, OTHER, [meta(OTHER), start, edit("2026-10-27T10:00:01Z", "/w/repo/a.py"),
                                      command("2026-10-27T10:00:02Z", "uv run pytest", 0),
                                      edit("2026-10-27T10:00:03Z", "/w/repo/b.py"), end])
    write_rollout(codex_home, SUBAGENT, [meta(SUBAGENT), start, edit("2026-10-27T10:00:01Z", "/w/repo/a.py"),
                                         command("2026-10-27T10:00:02Z", "uv run pytest", 0), end])
    docs = "0d3e1000-0000-7000-8000-000000000004"
    write_rollout(codex_home, docs, [meta(docs), start, edit("2026-10-27T10:00:01Z", "/w/repo/docs/SYNC.md"), end])
    search = "0d3e1000-0000-7000-8000-000000000005"
    write_rollout(codex_home, search, [meta(search), start, command("2026-10-27T10:00:01Z", "uv run pytest -q", 1),
                                       command("2026-10-27T10:00:02Z", "cd /w/repo && uv run pytest -q", 0),
                                       command("2026-10-27T10:00:03Z", "rg -n pytest pyproject.toml", 1), end])
    states = {entry["id"]: entry["check_state"] for entry in client(codex_home).get("/api/inbox").json()}

    assert states == {THREAD: "failed", OTHER: "unchecked", SUBAGENT: "", docs: "", search: ""}


def test_deleted_chat_is_not_found_instead_of_an_error(codex_home: Path) -> None:
    app = client(codex_home)
    assert app.get(f"/api/threads/{THREAD}").status_code == 200
    (codex_home / "sessions/2026/10/27" / f"rollout-2026-10-27T11-03-04-{THREAD}.jsonl").unlink()

    assert app.get(f"/api/threads/{THREAD}").status_code == 404


def test_stream_sends_the_current_inbox_first(codex_home: Path) -> None:
    polls = iter([False, True])
    app = TestClient(create_app(codex_home, poll_seconds=0, should_stop=lambda: next(polls, True)), base_url="http://127.0.0.1")

    with app.stream("GET", "/api/stream") as response:
        body = response.read().decode()
    head, data = body.split("\n", 2)[:2]
    assert head == "event: inbox"
    assert [entry["id"] for entry in json.loads(data.removeprefix("data: "))] == [THREAD]


def test_thread_state_and_bad_ids(codex_home: Path) -> None:
    app = client(codex_home)

    state = app.get(f"/api/threads/{THREAD}").json()
    assert (state["title"], state["turns"][0]["next_kind"]) == ("Fix login", "answer")
    assert app.get("/api/threads/not-a-thread").status_code == 400
    assert app.get(f"/api/threads/{OTHER}").status_code == 404
    assert app.get("/api/stream?thread=../x").status_code == 400


def test_serves_page_with_policy_and_only_loopback(codex_home: Path) -> None:
    app = client(codex_home)
    page = app.get("/")

    assert page.status_code == 200 and "script-src 'self'" in page.headers["content-security-policy"]
    assert app.get("/assets/app.js").headers["content-type"].startswith("text/javascript")
    assert app.get("/assets/icon-alert.svg").headers["content-type"].startswith("image/svg+xml")
    referenced = re.findall(r'(?:src|href)="(/assets/[^"]+)"', page.text)
    assert referenced and all(app.get(path).status_code == 200 for path in referenced)
    assert app.get("/assets/secrets.txt").status_code == 404
    assert app.get("/assets/index.html").status_code == 404
    assert app.get("/assets/missing.js").status_code == 404
    assert app.get("/assets/..%2Fapp.py").status_code == 404
    evil = TestClient(create_app(codex_home), base_url="http://evil.example")
    assert evil.get("/").status_code == 400


@pytest.mark.parametrize("name", ["header-light.webp", "header-dark.webp", "brand-leaf.webp"])
def test_serves_binary_artwork_without_text_decoding(codex_home: Path, name: str) -> None:
    app = client(codex_home)
    response = app.get(f"/assets/{name}")
    expected = files("yourturn").joinpath("static", name).read_bytes()
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    assert response.content == expected
    assert response.content[:4] == b"RIFF"
    assert response.headers["content-security-policy"].find("img-src 'self'") >= 0
    assert app.get("/assets/missing.webp").status_code == 404
    assert app.get("/assets/..%2Fheader-light.webp").status_code == 404


def test_mcp_server_offers_only_log_decision() -> None:
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "log_decision", "arguments": {"question": "q", "chosen": "A"}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "set_active_thread", "arguments": {}}},
    ]
    out = io.StringIO()
    serve(io.StringIO("".join(json.dumps(r) + "\n" for r in requests)), out)
    replies = {reply["id"]: reply for reply in map(json.loads, out.getvalue().splitlines())}

    assert set(replies) == {1, 2, 3, 4}
    assert "can I trust it" in replies[1]["result"]["instructions"]
    assert [tool["name"] for tool in replies[2]["result"]["tools"]] == ["log_decision"]
    assert replies[3]["result"]["content"][0]["text"] == "Recorded decision: A"
    assert replies[4]["result"]["isError"] is True


def test_page_footer_uses_application_version(codex_home: Path) -> None:
    from yourturn import __version__

    html = client(codex_home).get("/").text
    assert f'aria-label="Application version">v{__version__}</footer>' in html
    assert "{{APP_VERSION}}" not in html


def test_help_uses_configured_history(codex_home: Path) -> None:
    app = TestClient(create_app(codex_home, history_days=7), base_url="http://127.0.0.1")
    html = app.get("/").text
    assert "last 7 days" in html
    assert "{{HISTORY_DAYS}}" not in html


def test_inbox_and_thread_serve_claude_next_to_codex(codex_home: Path, tmp_path: Path) -> None:
    from test_claude_adapter import SID as CLAUDE, _turn, _write

    claude_home = tmp_path / "claude"
    _write(claude_home, _turn())
    polls = iter([False, True])
    app = TestClient(create_app(codex_home, claude_home=claude_home, should_stop=lambda: next(polls, True), poll_seconds=0),
                     base_url="http://127.0.0.1")

    inbox = app.get("/api/inbox").json()
    rows = {entry["key"]: entry for entry in inbox}
    assert set(rows) == {f"codex:{THREAD}", f"claude:{CLAUDE}"}
    assert [entry["updated_at"] for entry in inbox] == sorted((entry["updated_at"] for entry in inbox), reverse=True)
    claude = rows[f"claude:{CLAUDE}"]
    assert (claude["harness"], claude["title"], claude["project"], claude["status"]) == ("claude", "Fix parser", "my-repo", "done")
    assert claude["handoff"]["resume_command"] == f"claude --resume {CLAUDE}"
    assert rows[f"codex:{THREAD}"]["handoff"]["resume_command"] == f"codex resume {THREAD}"

    response = app.get(f"/api/threads/claude:{CLAUDE}")
    assert response.status_code == 200, response.text
    detail = response.json()
    assert (detail["key"], detail["harness"], detail["model_provider"], detail["status"]) == (
        f"claude:{CLAUDE}", "claude", "anthropic", "done")
    assert detail["turns"][-1]["outcome"] == "Fixed the bug."
    assert app.get(f"/api/threads/codex:{THREAD}").status_code == 200
    assert app.get(f"/api/threads/{THREAD}").json()["key"] == f"codex:{THREAD}"
    assert app.get("/api/threads/claude:not-a-uuid").status_code == 400
    assert app.get(f"/api/threads/cursor:{CLAUDE}").status_code == 404

    with app.stream("GET", f"/api/stream?thread=claude:{CLAUDE}") as stream:
        body = "".join(stream.iter_text())
    assert body.startswith("event: thread\n") and f'"key": "claude:{CLAUDE}"' in body
