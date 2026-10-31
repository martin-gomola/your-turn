from __future__ import annotations

import json
from pathlib import Path

import pytest

from yourturn.engine import TurnFolder
from yourturn.harness.codex import record_to_events
from yourturn.model import SessionRef

THREAD = "0d3e1000-0000-7000-8000-000000000001"
OTHER = "0d3e1000-0000-7000-8000-000000000002"
SUBAGENT = "0d3e1000-0000-7000-8000-000000000003"


def event(ts: str, payload: dict) -> dict:
    return {"timestamp": ts, "type": "event_msg", "payload": payload}


def item(ts: str, body: dict) -> dict:
    return event(ts, {"type": "item_completed", "thread_id": THREAD, "turn_id": "t1", "item": body})


def meta(thread_id: str, source: object = "vscode") -> dict:
    return {"timestamp": "2026-10-27T10:03:04Z", "type": "session_meta",
            "payload": {"id": thread_id, "cwd": "/w/repo", "timestamp": "2026-10-27T10:03:04Z", "source": source}}


def command(ts: str, cmd: str, exit_code: int) -> dict:
    return item(ts, {"type": "CommandExecution", "command": ["/bin/zsh", "-lc", cmd], "exit_code": exit_code})


def edit(ts: str, path: str) -> dict:
    return item(ts, {"type": "FileChange", "changes": {path: {"type": "update"}}})


RECORDS = [
    meta(THREAD),
    {"timestamp": "2026-10-27T10:03:05Z", "type": "response_item", "payload": {"type": "reasoning", "encrypted_content": "x" * 5000}},
    event("2026-10-27T10:03:05Z", {"type": "task_started", "turn_id": "t1"}),
    item("2026-10-27T10:03:06Z", {"type": "UserMessage", "content": [{"type": "text", "text":
         "<in-app-browser-context source=\"ambient\">noise</in-app-browser-context>\nFix the login bug"}]}),
    item("2026-10-27T10:03:07Z", {"type": "Reasoning", "summary_text": ["**Inspecting auth flow**"]}),
    command("2026-10-27T10:03:08Z", "uv run pytest -q", 1),
    edit("2026-10-27T10:03:09Z", "/w/repo/auth.py"),
    item("2026-10-27T10:03:10Z", {"type": "McpToolCall", "server": "your-turn", "tool": "log_decision", "status": "completed",
                                  "arguments": {"question": "Where to fix?", "options": ["Middleware", "Handler"], "chosen": "Handler", "reason": "Smaller change"}}),
    item("2026-10-27T10:03:11Z", {"type": "AgentMessage", "phase": "final_answer", "content": [{"type": "Text", "text": "Need input. More text."}],
                                  "questions": [{"title": "Ship now?", "options": ["Yes", "No"]}]}),
    event("2026-10-27T10:03:12Z", {"type": "token_count", "info": {"last_token_usage": {"total_tokens": 250}, "model_context_window": 1000}}),
    event("2026-10-27T10:03:12Z", {"type": "task_complete", "turn_id": "t1", "duration_ms": 7000}),
]


class Parser:
    """Folds raw Codex records into a `TurnFolder`, the way the Codex adapter's cursor does."""

    def __init__(self, thread_id: str = THREAD) -> None:
        self.state = TurnFolder(SessionRef(harness="codex", session_id=thread_id))

    def feed(self, record: dict) -> None:
        self.state.fold_many(record_to_events(record))


def write_rollout(codex_home: Path, thread_id: str, records: list[dict], day: str = "2026/10/27") -> Path:
    folder = codex_home / "sessions" / day
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"rollout-2026-10-27T11-03-04-{thread_id}.jsonl"
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    return path


def append(path: Path, *records: dict) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write("".join(json.dumps(record) + "\n" for record in records))


@pytest.fixture
def codex_home(tmp_path: Path) -> Path:
    home = tmp_path / "codex"
    write_rollout(home, THREAD, RECORDS)
    (home / "session_index.jsonl").write_text(
        json.dumps({"id": THREAD, "thread_name": "Old name"}) + "\n" + json.dumps({"id": THREAD, "thread_name": "Fix login"}) + "\n",
        encoding="utf-8",
    )
    return home
