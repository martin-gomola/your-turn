"""Transcript builders: made-up Codex, Claude Code and Cursor chats written in each agent's own on-disk format.

Times are minutes before `NOW`; each record moves the chat's clock 30 seconds closer to now.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

NOW = datetime.now(UTC)


def at(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class Chat:
    def __init__(self, number: int, title: str, project: str, started: float) -> None:
        self.id = f"0d3e{number:04x}-0000-7000-8000-{number:012x}"
        self.title, self.project, self.clock, self.turn = title, project, started, 0
        self.records: list[dict] = [
            {"timestamp": at(started), "type": "session_meta", "payload": {
                "id": self.id, "cwd": f"/workspace/{project}", "timestamp": at(started), "source": "vscode",
                "model_provider": "openai", "cli_version": "0.80.0", "git": {"branch": "main"}}},
            {"timestamp": at(started), "type": "turn_context", "payload": {"model": "gpt-5.5", "effort": "medium"}},
        ]

    def _add(self, record_type: str, payload: dict) -> None:
        self.clock -= 0.5
        self.records.append({"timestamp": at(self.clock), "type": record_type, "payload": payload})

    def _item(self, body: dict) -> None:
        self._add("event_msg", {"type": "item_completed", "thread_id": self.id, "turn_id": f"t{self.turn}", "item": body})

    def ask(self, prompt: str) -> Chat:
        self.turn += 1
        self._add("event_msg", {"type": "task_started", "turn_id": f"t{self.turn}"})
        self._item({"type": "UserMessage", "content": [{"type": "text", "text": prompt}]})
        return self

    def reply(self, question: str, answer: str) -> Chat:
        replies = json.dumps([{"question": question, "answer": answer}])
        return self.ask(f"<send_user_message_question_reply>{replies}</send_user_message_question_reply>")

    def think(self, summary: str) -> Chat:
        self._item({"type": "Reasoning", "summary_text": [summary]})
        return self

    def run(self, command: str, exit_code: int = 0) -> Chat:
        self._item({"type": "CommandExecution", "command": ["/bin/zsh", "-lc", command], "exit_code": exit_code})
        return self

    def edit(self, *paths: str) -> Chat:
        changes = {f"/workspace/{self.project}/{path}": {"type": "update"} for path in paths}
        self._item({"type": "FileChange", "changes": changes})
        return self

    def decide(self, question: str, options: list[str], chosen: str, reason: str) -> Chat:
        arguments = {"question": question, "options": options, "chosen": chosen, "reason": reason}
        self._item({"type": "McpToolCall", "server": "your-turn", "tool": "log_decision",
                    "status": "completed", "arguments": arguments})
        return self

    def answer(self, text: str, question: dict | None = None) -> Chat:
        body = {"type": "AgentMessage", "phase": "final_answer", "content": [{"type": "Text", "text": text}]}
        if question:
            body["questions"] = [question]
        self._item(body)
        self._add("event_msg", {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": 182_000, "cached_input_tokens": 120_000, "output_tokens": 9_400,
                                  "reasoning_output_tokens": 3_100, "total_tokens": 191_400},
            "last_token_usage": {"input_tokens": 61_000, "output_tokens": 1_800, "total_tokens": 62_800},
            "model_context_window": 258_000}})
        self._add("event_msg", {"type": "task_complete", "turn_id": f"t{self.turn}", "duration_ms": 184_000})
        return self

    def write(self, home: Path, held: int = 0) -> Path:
        """Write the session file, holding back the last `held` records for `append_held`."""
        folder = home / "sessions" / NOW.strftime("%Y/%m/%d")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"rollout-{NOW.strftime('%Y-%m-%dT%H-%M-%S')}-{self.id}.jsonl"
        records = self.records[:len(self.records) - held]
        path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
        mtime = (NOW - timedelta(minutes=self.clock)).timestamp()
        if not held:
            os.utime(path, (mtime, mtime))
        return path

    def append_held(self, path: Path, held: int) -> None:
        with path.open("a", encoding="utf-8") as file:
            file.write("".join(json.dumps(record) + "\n" for record in self.records[-held:]))


# Chat.answer adds the final message, a token count and task_complete.
ANSWER_RECORDS = 3


def _touch(path: Path, minutes_ago: float) -> None:
    stamp = (NOW - timedelta(minutes=minutes_ago)).timestamp()
    os.utime(path, (stamp, stamp))


class ClaudeChat:
    """A made-up Claude Code transcript (`<home>/projects/<slug>/<id>.jsonl`)."""

    def __init__(self, number: int, title: str, project: str, started: float) -> None:
        self.id = f"c1a0{number:04x}-0000-4000-8000-{number:012x}"
        self.title, self.project, self.clock, self.tools = title, project, started, 0
        self.records: list[dict] = [{"type": "custom-title", "customTitle": title, "sessionId": self.id}]

    def _add(self, kind: str, **fields: object) -> None:
        self.clock -= 0.5
        self.records.append({"type": kind, "timestamp": at(self.clock), "sessionId": self.id, "cwd": f"/workspace/{self.project}",
                             "gitBranch": "main", "version": "2.1.0", "isSidechain": False, **fields})

    def _assistant(self, block: dict, stop: str = "tool_use") -> None:
        self.tools += 1
        self._add("assistant", effort="high", message={
            "model": "claude-opus-4-5", "id": f"msg{self.tools}", "role": "assistant", "content": [block], "stop_reason": stop,
            "usage": {"input_tokens": 1_200, "cache_creation_input_tokens": 2_400, "cache_read_input_tokens": 38_000, "output_tokens": 900}})

    def _tool(self, name: str, arguments: dict, result: str | None = "", error: bool = False) -> ClaudeChat:
        self._assistant({"type": "tool_use", "id": f"tool{self.tools}", "name": name, "input": arguments})
        if result is not None:
            self._add("user", message={"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"tool{self.tools - 1}", "content": result, "is_error": error}]})
        return self

    def ask(self, prompt: str) -> ClaudeChat:
        self._add("user", message={"role": "user", "content": prompt})
        return self

    def think(self, text: str) -> ClaudeChat:
        self._assistant({"type": "thinking", "thinking": text, "signature": "demo"})
        return self

    def run(self, command: str, error: bool = False) -> ClaudeChat:
        return self._tool("Bash", {"command": command, "description": "Run checks"}, "FAILED" if error else "ok", error)

    def edit(self, *paths: str) -> ClaudeChat:
        for path in paths:
            self._tool("Edit", {"file_path": f"/workspace/{self.project}/{path}", "old_string": "a", "new_string": "b"})
        return self

    def question(self, title: str, options: list[str]) -> ClaudeChat:
        """AskUserQuestion with no answer yet: the chat waits on the user."""
        return self._tool("AskUserQuestion", {"questions": [{"question": title, "header": "Choice", "multiSelect": False,
                                                             "options": [{"label": o, "description": o} for o in options]}]}, None)

    def write(self, home: Path) -> Path:
        folder = home / "projects" / f"-workspace-{self.project}"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{self.id}.jsonl"
        path.write_text("".join(json.dumps(record) + "\n" for record in self.records), encoding="utf-8")
        _touch(path, self.clock)
        return path


class CursorChat:
    """A made-up Cursor agent transcript plus its `composerHeaders` row."""

    def __init__(self, number: int, title: str, project: str, started: float, *, approval: bool = False) -> None:
        self.id = f"c0a5{number:04x}-0000-4000-8000-{number:012x}"
        self.title, self.project, self.started, self.approval = title, project, started, approval
        self.records: list[dict] = []

    def ask(self, prompt: str) -> CursorChat:
        local = (NOW - timedelta(minutes=self.started)).strftime("%A, %b %d, %Y, %I:%M %p")
        self.records.append({"role": "user", "message": {"content": [
            {"type": "text", "text": f"<timestamp>{local} (UTC+0)</timestamp>\n<user_query>\n{prompt}\n</user_query>"}]}})
        return self

    def say(self, text: str, *tools: tuple[str, dict]) -> CursorChat:
        content = [{"type": "text", "text": text}] + [{"type": "tool_use", "name": name, "input": args} for name, args in tools]
        self.records.append({"role": "assistant", "message": {"content": content}})
        return self

    def write(self, home: Path, database: sqlite3.Connection, minutes_ago: float) -> Path:
        folder = home / "projects" / f"workspace-{self.project}" / "agent-transcripts" / self.id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{self.id}.jsonl"
        path.write_text("".join(json.dumps(record) + "\n" for record in self.records), encoding="utf-8")
        _touch(path, minutes_ago)
        millis = lambda minutes: int((NOW - timedelta(minutes=minutes)).timestamp() * 1000)  # noqa: E731
        cwd = f"/workspace/{self.project}"
        value = {"composerId": self.id, "name": self.title, "createdAt": millis(self.started), "lastUpdatedAt": millis(minutes_ago),
                 "hasBlockingPendingActions": self.approval, "workspaceIdentifier": {"id": "demo", "uri": {"fsPath": cwd, "scheme": "file"}}}
        database.execute("INSERT INTO composerHeaders VALUES (?, 'demo', ?, ?, 0, 0, ?)",
                         (self.id, value["createdAt"], value["lastUpdatedAt"], json.dumps(value)))
        return path

