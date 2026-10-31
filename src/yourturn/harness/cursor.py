"""Cursor harness adapter: tails Cursor agent transcripts and reads composer metadata read-only.

Events come from `~/.cursor/projects/<slug>/agent-transcripts/<composerId>/<composerId>.jsonl`:
`{role, message: {content: [text | tool_use]}}` records plus `{type: "turn_ended", status}`. They
carry no tool results and no timestamps except the `<timestamp>` tag in each user prompt, so
commands have no exit code and every event is stamped with its turn's prompt time.

Title, workspace folder, archived and sub-agent flags, and whether the composer is blocked on an
approval (`hasBlockingPendingActions`) come from the `composerHeaders` table of
Cursor's `globalStorage/state.vscdb`, opened with `mode=ro` (never written, WAL included).
"""

from __future__ import annotations

import dataclasses
import json
import re
import shlex
import sqlite3
import sys
import time
from collections.abc import Callable, Iterator
from functools import lru_cache
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

from yourturn.harness.base import (
    AgentMessage,
    ApprovalPending,
    CommandRun,
    Event,
    FilesEdited,
    Meta,
    ToolCall,
    TurnEnded,
    TurnStarted,
    UserMessage,
)
from yourturn.harness.codex import ASK_USER_TOOL, DECISION_TOOL, SUBAGENT_TOOL, TURN_COMPLETED, CodexCursor, _command
from yourturn.heuristics import clip
from yourturn.model import Capabilities, Handoff, Harness, SessionRef

TRANSCRIPT_GLOB = "*/agent-transcripts/*/*.jsonl"  # Sub-agent transcripts live deeper, in .../subagents/.
EDIT_TOOLS = {"StrReplace": "path", "Write": "path", "Delete": "path", "EditNotebook": "target_notebook"}
TAG_BLOCK = re.compile(r"<([\w-]+)>.*?</\1>", re.DOTALL)
USER_QUERY = re.compile(r"<user_query>\s*(.*?)\s*</user_query>", re.DOTALL)
PROMPT_TIME = re.compile(r"<timestamp>\s*(.*?)\s*</timestamp>", re.DOTALL)
PATCH_FILE = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$", re.MULTILINE)
APPROVAL_TEXT = "Approve pending action in Cursor"
UTC_OFFSET = re.compile(r"\(UTC([+-])(\d{1,2})(?::(\d\d))?\)")


def cursor_home() -> Path:
    return Path.home() / ".cursor"


def cursor_user_dir() -> Path:
    """Cursor's VS Code-style user data folder (holds `globalStorage/state.vscdb`)."""
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Cursor" / "User"
    if sys.platform == "win32":
        return Path.home() / "AppData" / "Roaming" / "Cursor" / "User"
    return Path.home() / ".config" / "Cursor" / "User"


def parse_prompt_time(text: str) -> datetime | None:
    """`Friday, Oct 31, 2026, 9:05 AM (UTC+2)` -> aware datetime; None when absent or unreadable."""
    match = PROMPT_TIME.search(text)
    if match is None:
        return None
    raw = match.group(1)
    offset = UTC_OFFSET.search(raw)
    try:
        local = datetime.strptime(UTC_OFFSET.sub("", raw).strip(), "%A, %b %d, %Y, %I:%M %p")
    except ValueError:
        return None
    delta = timedelta(hours=int(offset.group(2)), minutes=int(offset.group(3) or 0)) if offset else timedelta()
    return local.replace(tzinfo=timezone(-delta if offset and offset.group(1) == "-" else delta))


def prompt_text(text: str) -> str:
    """What the user typed: the `<user_query>` block, else the text outside Cursor's context tags."""
    match = USER_QUERY.search(text)
    return (match.group(1) if match else TAG_BLOCK.sub("", text)).strip()


@lru_cache(maxsize=1024)
def decode_slug(slug: str) -> str | None:
    """`work-dev-my-repo` -> `/work/dev/my-repo`, joining parts greedily while the path exists."""
    path, parts = Path("/"), slug.split("-")
    while parts:
        for size in range(len(parts), 0, -1):
            candidate = path / "-".join(parts[:size])
            if candidate.exists():
                path, parts = candidate, parts[size:]
                break
        else:
            return None
    return str(path) if path != Path("/") else None


def _epoch_ms(value: object) -> datetime | None:
    return datetime.fromtimestamp(value / 1000, timezone.utc) if type(value) is int and value > 0 else None


def _edited_paths(name: str, arguments: object) -> tuple[str, ...]:
    if name == "ApplyPatch":
        return tuple(PATCH_FILE.findall(arguments if isinstance(arguments, str) else ""))
    path = arguments.get(EDIT_TOOLS[name]) if isinstance(arguments, dict) else None
    return (str(path),) if path else ()


class CursorCursor(CodexCursor):
    """Incremental reader over one Cursor agent transcript (implements `EventCursor`)."""

    def __init__(
        self,
        ref: SessionRef,
        title: str = "",
        created: datetime | None = None,
        header: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(ref)
        self._title = title
        self._created = created
        # The adapter's latest composerHeaders row for this session (refreshed on each discover).
        self._header = header or dict
        self._clear()

    def _clear(self) -> None:
        self._meta_sent = False
        self._ts: datetime | None = None
        self._asked: list[str] = []
        self._approval = False

    def reset(self) -> None:
        super().reset()
        self._clear()

    def _head_events(self) -> list[Event]:
        return self._meta()

    def _parse(self, raw: bytes) -> dict[str, Any] | None:
        try:
            record = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return None
        return record if isinstance(record, dict) else None

    def _meta(self) -> list[Event]:
        if self._meta_sent:
            return []
        self._meta_sent = True
        return [
            Meta(
                ts=self._created,
                session_id=self._ref.session_id,
                cwd=self._ref.cwd or "",
                harness=Harness.CURSOR.value,
                model_provider="cursor",
                title=self._title or None,
                subagent=False,
                parent_id="",
            )
        ]

    def read_new(self) -> list[Event]:
        events = super().read_new()
        if events and isinstance(events[-1], TurnEnded):
            # The latest turn ended no later than the transcript's last write.
            try:
                ended = datetime.fromtimestamp(self._path.stat().st_mtime, timezone.utc)
                events[-1] = dataclasses.replace(events[-1], ts=ended)
            except OSError:
                pass
        # The approval flag changes in Cursor's database, not in the transcript: report each flip.
        header = self._header()
        pending = bool(header.get("pending"))
        if pending != self._approval:
            self._approval = pending
            events.append(ApprovalPending(ts=header.get("updated"), pending=pending, text=APPROVAL_TEXT))
        return events

    def _events(self, record: dict[str, Any]) -> list[Event]:
        events = self._meta()
        if record.get("type") == "turn_ended":
            ok = record.get("status") == "success"
            return events + [TurnEnded(ts=self._ts, reason=TURN_COMPLETED if ok else str(record.get("error") or "error"))]
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        content = message.get("content") if isinstance(message.get("content"), list) else []
        blocks = [block for block in content if isinstance(block, dict)]
        if record.get("role") == "user":
            raw = "\n".join(block["text"] for block in blocks if block.get("type") == "text" and isinstance(block.get("text"), str))
            text = prompt_text(raw)
            if not text:
                return events
            self._ts = parse_prompt_time(raw) or self._ts
            self._asked = []
            return events + [TurnStarted(ts=self._ts), UserMessage(ts=self._ts, text=text)]
        if record.get("role") != "assistant":
            return events
        if self._asked:
            # The agent carried on, so the user answered in Cursor; the transcript does not say what,
            # so the answer text stays empty ("answered, text not recorded").
            events.append(UserMessage(ts=self._ts, answers=tuple((title, "") for title in self._asked)))
            self._asked = []
        for block in blocks:
            if block.get("type") == "text" and isinstance(block.get("text"), str) and block["text"].strip():
                events.append(AgentMessage(ts=self._ts, text=block["text"]))
            elif block.get("type") == "tool_use":
                events.extend(self._tool(str(block.get("name") or ""), block.get("input")))
        return events

    def _tool(self, name: str, arguments: Any) -> list[Event]:
        args = arguments if isinstance(arguments, dict) else {}
        if name == "Shell":
            return [CommandRun(ts=self._ts, command=_command({"command": args.get("command") or ""}))]
        if name in EDIT_TOOLS or name == "ApplyPatch":
            return [FilesEdited(ts=self._ts, paths=_edited_paths(name, arguments))]
        if name == "AskQuestion":
            events: list[Event] = []
            for question in args.get("questions") or []:
                if not isinstance(question, dict):
                    continue
                title = clip(str(question.get("prompt", "")))
                options = [str(option.get("label", "")) for option in question.get("options") or [] if isinstance(option, dict)]
                self._asked.append(title)
                events.append(ToolCall(ts=self._ts, name=ASK_USER_TOOL, arguments=json.dumps({"title": title, "options": options}, ensure_ascii=False)))
            return events
        if name == "Task":
            return [ToolCall(ts=self._ts, name=SUBAGENT_TOOL, arguments=str(args.get("description") or args.get("subagent_type") or name), ok=True)]
        text = json.dumps(arguments, ensure_ascii=False) if arguments is not None else None
        if name == "CallMcpTool":
            tool = str(args.get("toolName") or "")
            if tool == DECISION_TOOL:
                return [ToolCall(ts=self._ts, name=DECISION_TOOL, arguments=json.dumps(args.get("arguments") or {}, ensure_ascii=False), ok=True)]
            return [ToolCall(ts=self._ts, name=f"{args.get('server')} · {tool}", arguments=text)]
        return [ToolCall(ts=self._ts, name=name, arguments=text)]


class CursorAdapter:
    """Finds Cursor agent transcripts and opens cursors on them (implements `HarnessAdapter`)."""

    name: str = Harness.CURSOR.value
    capabilities: Capabilities = Capabilities(
        can_resume=False,
        has_tool_calls=True,
        has_checks=True,
        live_tail=True,
        turn_boundaries=True,
        approval_prompts=True,
        structured_questions=True,
    )

    def __init__(
        self,
        home: Path | None = None,
        *,
        user_dir: Path | None = None,
        include_subagents: bool = False,
        max_age_days: float | None = None,
    ) -> None:
        self.home = home or cursor_home()
        self.user_dir = user_dir or cursor_user_dir()
        self.include_subagents = include_subagents
        self.max_age_days = max_age_days
        self._headers: dict[str, dict[str, Any]] = {}

    def available(self) -> bool:
        return (self.home / "projects").is_dir()

    def _read_headers(self) -> dict[str, dict[str, Any]]:
        """composerId -> {title, cwd, archived, subagent} from Cursor's composer index ({} if unreadable)."""
        database = self.user_dir / "globalStorage" / "state.vscdb"
        if not database.is_file():
            return {}
        headers: dict[str, dict[str, Any]] = {}
        try:
            # Read-only URI: Cursor owns this database and its WAL; we never write or checkpoint it.
            with sqlite3.connect(f"file:{quote(str(database))}?mode=ro", uri=True, timeout=1.0) as connection:
                rows = connection.execute("SELECT composerId, isArchived, isSubagent, value FROM composerHeaders").fetchall()
        except sqlite3.Error:
            return {}
        for composer_id, archived, subagent, value in rows:
            try:
                data = json.loads(value) if value else {}
            except (TypeError, json.JSONDecodeError):
                data = {}
            workspace = data.get("workspaceIdentifier") if isinstance(data, dict) else None
            uri = workspace.get("uri") if isinstance(workspace, dict) else None
            headers[str(composer_id)] = {
                "title": str(data.get("name") or "") if isinstance(data, dict) else "",
                "cwd": uri.get("fsPath") if isinstance(uri, dict) and isinstance(uri.get("fsPath"), str) else None,
                "created": _epoch_ms(data.get("createdAt") if isinstance(data, dict) else None),
                "updated": _epoch_ms(data.get("lastUpdatedAt") if isinstance(data, dict) else None),
                "pending": bool(data.get("hasBlockingPendingActions")) if isinstance(data, dict) else False,
                "archived": bool(archived),
                "subagent": bool(subagent),
            }
        return headers

    def discover(self, root: Path | None = None) -> Iterator[SessionRef]:
        projects = (root if root is not None and (root / "projects").is_dir() else self.home) / "projects"
        if not projects.is_dir():
            return
        found: list[tuple[float, Path]] = []
        for path in projects.glob(TRANSCRIPT_GLOB):
            try:
                found.append((path.stat().st_mtime, path))
            except OSError:
                continue
        found.sort(reverse=True)
        cutoff = time.time() - self.max_age_days * 86400 if self.max_age_days is not None else None
        self._headers = self._read_headers()
        for mtime, path in found:
            # Each transcript is its session's own file, so its mtime is that session's last activity.
            if cutoff is not None and mtime < cutoff:
                break
            header = self._headers.get(path.stem, {})
            if header.get("archived") or (header.get("subagent") and not self.include_subagents):
                continue
            cwd = header.get("cwd") or decode_slug(path.parents[2].name)
            yield SessionRef(harness=self.name, session_id=path.stem, path=path, cwd=cwd)

    def open(self, ref: SessionRef) -> CursorCursor:
        return CursorCursor(
            ref,
            self.title(ref),
            self._headers.get(ref.session_id, {}).get("created"),
            header=lambda: self._headers.get(ref.session_id, {}),
        )

    def state_token(self, ref: SessionRef) -> str:
        """Changes when Cursor's own state for the session changes (activity, pending approvals)."""
        header = self._headers.get(ref.session_id, {})
        return f"{header.get('updated')}:{header.get('pending', False)}"

    def title(self, ref: SessionRef) -> str:
        return str(self._headers.get(ref.session_id, {}).get("title") or "")

    def handoff(self, ref: SessionRef, cwd: str | None) -> Handoff:
        where = cwd or ref.cwd
        if not where:
            return Handoff()
        return Handoff(resume_command=f"cursor {shlex.quote(where)}", open_path=where, open_uri=f"cursor://file{quote(where)}", terminal_cwd=where)

    @staticmethod
    def project(ref: SessionRef) -> str:
        if ref.cwd:
            return Path(ref.cwd).name
        return ref.path.parents[2].name if ref.path else ""
