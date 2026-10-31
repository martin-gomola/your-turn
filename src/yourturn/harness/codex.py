"""Codex harness adapter: tails rollout JSONL files and maps records to normalized events.

Read-only: files under the Codex home are only ever opened in binary read mode. No subprocesses,
no network. The record shapes and helpers here are the single source of truth for Codex rollout
parsing; `yourturn.rollout` imports them back.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from yourturn.harness.base import (
    AgentMessage,
    CommandRun,
    ContextCompacted,
    Event,
    FilesEdited,
    Meta,
    Reasoning,
    ToolCall,
    TurnEnded,
    TurnStarted,
    Usage,
    UserMessage,
)
from yourturn.heuristics import clip as _clip
from yourturn.model import Capabilities, Handoff, Harness, SessionRef

# --- Shared Codex rollout knowledge (re-exported by yourturn.rollout) ---------------------------

ROLLOUT_GLOB = "*/*/*/rollout-*.jsonl"
DECISION_TOOL = "log_decision"
# Synthetic ToolCall name for a question the agent asked the user (Codex carries them on AgentMessage).
ASK_USER_TOOL = "ask_user"
# Synthetic ToolCall name for a sub-agent being started.
SUBAGENT_TOOL = "subagent"
# Substring prefilter: rollout files carry multi-megabyte encrypted reasoning lines we never need to parse.
WANTED = (b'"item_completed"', b'"task_started"', b'"task_complete"', b'"turn_aborted"', b'"session_meta"', b'"turn_context"', b'"token_count"')
TOKEN_FIELDS = ("input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens")
SHELL_WRAPPERS = {"-lc", "-c"}
QUESTION_REPLY = re.compile(r"<send_user_message_question_reply>\s*(.*?)\s*</send_user_message_question_reply>", re.DOTALL)
# Codex prepends app and environment context to user messages; it is not what the user typed.
INJECTED_CONTEXT = re.compile(r"<([\w-]*context[\w-]*|user_instructions)\b[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
TURN_COMPLETED = "completed"
OUTPUT_TAIL = 400


def _token_counts(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {key: value[key] for key in TOKEN_FIELDS if type(value.get(key)) is int and value[key] >= 0}


def _texts(content: object) -> str:
    if not isinstance(content, list):
        return ""
    return "\n".join(part["text"] for part in content if isinstance(part, dict) and isinstance(part.get("text"), str))


def _command(item: dict[str, Any]) -> str:
    command = item.get("command")
    if isinstance(command, list):
        shell = len(command) >= 3 and command[-2] in SHELL_WRAPPERS
        command = command[-1] if shell else " ".join(map(str, command))
    lines = str(command or "").strip().splitlines()
    return _clip(lines[0] if lines else "", 120)


def is_background(source: object) -> bool:
    """Not a chat the user opened: a sub-agent thread, or a headless `codex exec` run (no chat in Codex)."""
    return (isinstance(source, dict) and "subagent" in source) or source == "exec"


def user_text(text: str) -> str:
    return INJECTED_CONTEXT.sub("", text).strip()


def thread_id_of(path: Path) -> str:
    return path.stem[-36:]


def codex_home() -> Path:
    """`$CODEX_HOME`, else `~/.codex` (Codex's own default)."""
    raw = os.environ.get("CODEX_HOME")
    return Path(raw).expanduser() if raw else Path.home() / ".codex"


class _Stamp(datetime):
    """A parsed rollout timestamp that keeps its source text, so `format_ts` echoes it unchanged."""

    raw = ""


def parse_ts(value: object) -> datetime | None:
    """Parse a rollout ISO timestamp (`...Z`) into an aware UTC datetime; None when absent/bad."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = _Stamp.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed.raw = value
    return parsed


def format_ts(value: datetime | None) -> str:
    """Inverse of `parse_ts` for `Step.at` / `Check.at` strings ("" when unknown)."""
    if value is None:
        return ""
    if isinstance(value, _Stamp) and value.raw:
        return value.raw
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _int_or_none(value: object) -> int | None:
    return value if type(value) is int else None


def _str_or_none(value: object, limit: int = 120) -> str | None:
    return _clip(value, limit) if isinstance(value, str) else None


# --- Record -> event mapping ---------------------------------------------------------------------


def record_to_events(record: dict[str, Any]) -> list[Event]:
    """Map one rollout record to normalized events (pure).

    Each understood record yields exactly one event, so `TurnFolder.version` counts records.
    """
    payload = record.get("payload")
    if not isinstance(payload, dict):
        return []
    ts = parse_ts(record.get("timestamp"))
    kind = record.get("type")
    if kind == "session_meta":
        git = payload.get("git") if isinstance(payload.get("git"), dict) else {}
        source = payload.get("source")
        return [
            Meta(
                ts=parse_ts(payload.get("timestamp")) or ts,
                session_id=str(payload["id"]) if payload.get("id") else None,
                cwd=str(payload.get("cwd", "")),
                harness=Harness.CODEX.value,
                model_provider=_str_or_none(payload.get("model_provider")),
                originator=_str_or_none(payload.get("originator")),
                cli_version=_str_or_none(payload.get("cli_version")),
                git_branch=_str_or_none(git.get("branch"), 160),
                git_commit=git["commit_hash"] if isinstance(git.get("commit_hash"), str) else None,
                git_repo_url=git["repository_url"] if isinstance(git.get("repository_url"), str) else None,
                subagent=isinstance(source, dict) and "subagent" in source,
                parent_id=str(payload.get("parent_thread_id") or ""),
            )
        ]
    if kind == "turn_context":
        # Each turn restates its settings: a missing value clears the previous one.
        return [
            Meta(
                ts=ts,
                model=_str_or_none(payload.get("model")) or "",
                reasoning_effort=_str_or_none(payload.get("effort"), 80) or "",
            )
        ]
    if kind != "event_msg":
        # TODO: legacy rollouts (`response_item` function_call/local_shell_call, event_msg
        # user_message/agent_message/exec_command_end/patch_apply_end) are not mapped; rollout.py
        # never parsed them either, and mapping both shapes would double-count newer files.
        return []
    event = payload.get("type")
    turn_id = str(payload["turn_id"]) if payload.get("turn_id") else None
    if event == "task_started":
        return [TurnStarted(ts=ts, turn_id=turn_id)]
    if event == "task_complete":
        duration = payload.get("duration_ms")
        duration_ms = duration if isinstance(duration, (int, float)) else None
        return [TurnEnded(ts=ts, turn_id=turn_id, reason=TURN_COMPLETED, duration_ms=duration_ms)]
    if event == "turn_aborted":
        # Any reason other than TURN_COMPLETED (including "") means the turn was stopped.
        return [TurnEnded(ts=ts, turn_id=turn_id, reason=str(payload.get("reason", "")))]
    if event == "token_count":
        info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
        total = _token_counts(info.get("total_token_usage"))
        window = info.get("model_context_window")
        return [
            Usage(
                ts=ts,
                input_tokens=total.get("input_tokens", 0),
                output_tokens=total.get("output_tokens", 0),
                cached_input_tokens=total.get("cached_input_tokens", 0),
                total_tokens=total.get("total_tokens", 0),
                total=total,
                last=_token_counts(info.get("last_token_usage")),
                window=window if type(window) is int and window >= 0 else None,
            )
        ]
    if event == "item_completed" and isinstance(payload.get("item"), dict):
        return _item_events(ts, payload["item"])
    return []


def _item_events(ts: datetime | None, item: dict[str, Any]) -> list[Event]:
    kind = item.get("type")
    if kind == "UserMessage":
        text = user_text(_texts(item.get("content")))
        match = QUESTION_REPLY.search(text)
        if match is None:
            return [UserMessage(ts=ts, text=text)]
        try:
            replies = json.loads(match.group(1))
        except json.JSONDecodeError:
            replies = []
        answers = tuple(
            (_clip(str(reply.get("question", ""))), _clip(str(reply.get("answer", "")), 120))
            for reply in (replies if isinstance(replies, list) else [])
            if isinstance(reply, dict)
        )
        # A reply block without readable answers is not a prompt either.
        return [UserMessage(ts=ts, text=text if answers else "", answers=answers)]
    if kind == "AgentMessage":
        phase = item.get("phase")
        questions = tuple(question for question in item.get("questions") or [] if isinstance(question, dict))
        return [AgentMessage(ts=ts, text=_texts(item.get("content")), phase=str(phase) if phase else None, questions=questions)]
    if kind == "Reasoning":
        return [Reasoning(ts=ts, text=" ".join(item.get("summary_text") or []))]
    if kind == "ContextCompaction":
        return [ContextCompacted(ts=ts)]
    if kind == "CommandExecution":
        output = item.get("aggregated_output")
        return [
            CommandRun(
                ts=ts,
                command=_command(item),
                exit_code=_int_or_none(item.get("exit_code")),
                duration_ms=_int_or_none(item.get("duration_ms")),
                output_tail=output[-OUTPUT_TAIL:] if isinstance(output, str) and output else None,
            )
        ]
    if kind == "FileChange":
        changes = item.get("changes")
        paths = tuple(str(path) for path in changes) if isinstance(changes, dict) else ()
        status = item.get("status")
        ok = True if status == "completed" else False if status == "failed" else None
        return [FilesEdited(ts=ts, paths=paths, ok=ok)]
    if kind == "McpToolCall":
        arguments = item.get("arguments")
        args_text = json.dumps(arguments, ensure_ascii=False) if arguments is not None else None
        if item.get("tool") == DECISION_TOOL:
            return [ToolCall(ts=ts, name=DECISION_TOOL, arguments=args_text, ok=True)]
        failed = item.get("status") not in ("completed", None)
        return [ToolCall(ts=ts, name=f"{item.get('server')} · {item.get('tool')}", arguments=args_text, ok=not failed)]
    if kind == "SubAgentActivity" and item.get("kind") == "started":
        return [ToolCall(ts=ts, name=SUBAGENT_TOOL, arguments=str(item.get("agent_path") or item.get("agent_thread_id")), ok=True)]
    return []


def parse_line(raw: bytes) -> dict[str, Any] | None:
    """One complete JSONL line -> record dict, or None when filtered out or malformed."""
    if not any(marker in raw for marker in WANTED):
        return None
    try:
        record = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        return None
    return record if isinstance(record, dict) else None


# --- Cursor --------------------------------------------------------------------------------------


class CodexCursor:
    """Byte-offset incremental reader over one rollout file (implements `EventCursor`).

    Other JSONL harnesses subclass it and override `_parse`, `_events` and `_head_events`.
    """

    def __init__(self, ref: SessionRef) -> None:
        if ref.path is None:
            raise ValueError("CodexCursor needs a SessionRef with a path")
        self._ref = ref
        self._path: Path = ref.path
        self._offset = 0
        self._skip_partial = False
        self._head: list[Event] = []
        # Bumped whenever the file shrank and the cursor rewound; consumers must rebuild state.
        self.truncations = 0

    @property
    def ref(self) -> SessionRef:
        return self._ref

    @property
    def offset(self) -> int:
        return self._offset

    @property
    def path(self) -> Path:
        return self._path

    def reset(self) -> None:
        self._offset = 0
        self._skip_partial = False
        self._head = []

    def skip_to_tail(self, max_bytes: int) -> None:
        """Before the first read, start `max_bytes` from the end (keeping the session_meta header)."""
        try:
            size = self._path.stat().st_size
        except OSError:
            return
        self.seek(max(0, size - max_bytes))

    def seek(self, start: int) -> None:
        """Before the first read, start at byte `start` (keeping the session_meta header).

        The first partial line after the seek point is discarded.
        """
        if self._offset != 0 or start <= 0:
            return
        self._offset, self._skip_partial = start, True
        try:
            self._head = self._head_events()
        except (OSError, ValueError, TypeError, AttributeError):
            self._head = []

    def _head_events(self) -> list[Event]:
        """Header events replayed when reading starts mid-file: the session_meta first line."""
        with self._path.open("rb") as handle:
            metadata = json.loads(handle.readline())
        if isinstance(metadata, dict) and metadata.get("type") == "session_meta":
            return record_to_events(metadata)
        return []

    def _parse(self, raw: bytes) -> dict[str, Any] | None:
        return parse_line(raw)

    def _events(self, record: dict[str, Any]) -> list[Event]:
        return record_to_events(record)

    def read_new(self) -> list[Event]:
        events, self._head = self._head, []
        try:
            size = self._path.stat().st_size
        except OSError:
            return events
        if size < self._offset:
            self.reset()
            self.truncations += 1
        if size <= self._offset:
            return events
        try:
            # Line by line: rollouts can be hundreds of megabytes and must not be loaded whole.
            with self._path.open("rb") as handle:
                handle.seek(self._offset)
                while self._offset < size:
                    raw = handle.readline()
                    if not raw.endswith(b"\n"):
                        break
                    self._offset += len(raw)
                    if self._skip_partial:
                        self._skip_partial = False
                        continue
                    record = self._parse(raw)
                    if record is None:
                        continue
                    # One unexpected record must not stop the rest of the file from being read.
                    try:
                        events.extend(self._events(record))
                    except (TypeError, AttributeError, ValueError):
                        continue
        except OSError:
            pass
        return events


# --- Adapter -------------------------------------------------------------------------------------


class CodexAdapter:
    """Finds Codex rollouts and opens cursors on them (implements `HarnessAdapter`)."""

    name: str = Harness.CODEX.value
    capabilities: Capabilities = Capabilities(
        can_resume=True,
        has_diffs=False,  # FileChange items name paths; we do not extract diff hunks.
        has_usage=True,
        has_tool_calls=True,
        has_checks=True,
        live_tail=True,
        turn_boundaries=True,
        exit_codes=True,
        structured_questions=True,
    )

    def __init__(
        self,
        home: Path | None = None,
        *,
        include_subagents: bool = False,
        max_age_days: float | None = None,
    ) -> None:
        self.home = home
        self.include_subagents = include_subagents
        self.max_age_days = max_age_days
        self._heads: dict[Path, tuple[bool, str | None]] = {}
        self._titles: tuple[float, dict[str, str]] = (-1.0, {})
        self._index: Path | None = None

    def _sessions_dir(self, root: Path | None) -> Path:
        if root is None:
            return (self.home or codex_home()) / "sessions"
        # Accept either the sessions directory itself or a Codex home containing one.
        return root / "sessions" if (root / "sessions").is_dir() else root

    def _head(self, path: Path) -> tuple[bool, str | None]:
        """(is_background, cwd) from the session_meta first line; cached since it never changes."""
        cached = self._heads.get(path)
        if cached is None:
            subagent, cwd = False, None
            try:
                with path.open("rb") as handle:
                    meta = json.loads(handle.readline())
                payload = meta.get("payload", {}) if isinstance(meta, dict) else {}
                if isinstance(payload, dict):
                    source = payload.get("source")
                    subagent = is_background(source)
                    cwd = str(payload["cwd"]) if payload.get("cwd") else None
            except (OSError, ValueError, AttributeError):
                pass
            cached = self._heads[path] = (subagent, cwd)
        return cached

    def discover(self, root: Path | None = None) -> Iterator[SessionRef]:
        sessions = self._sessions_dir(root)
        self._index = sessions.parent / "session_index.jsonl"
        found: list[tuple[float, Path]] = []
        for path in sessions.glob(ROLLOUT_GLOB):
            try:
                found.append((path.stat().st_mtime, path))
            except OSError:
                continue
        found.sort(reverse=True)
        cutoff = time.time() - self.max_age_days * 86400 if self.max_age_days is not None else None
        for mtime, path in found:
            if cutoff is not None and mtime < cutoff:
                break
            subagent, cwd = self._head(path)
            if subagent and not self.include_subagents:
                continue
            yield SessionRef(harness=self.name, session_id=thread_id_of(path), path=path, cwd=cwd)

    def open(self, ref: SessionRef) -> CodexCursor:
        return CodexCursor(ref)

    def handoff(self, ref: SessionRef, cwd: str | None) -> Handoff:
        where = cwd or ref.cwd
        return Handoff(resume_command=f"codex resume {ref.session_id}", open_path=where, terminal_cwd=where)

    def title(self, ref: SessionRef) -> str:
        """Chat title from Codex's `session_index.jsonl` ("" when unknown)."""
        index = self._index or (self.home or codex_home()) / "session_index.jsonl"
        try:
            modified = index.stat().st_mtime
        except OSError:
            return ""
        if modified != self._titles[0]:
            titles: dict[str, str] = {}
            try:
                lines = index.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                return ""
            for line in lines:
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict) and entry.get("id"):
                    titles[str(entry["id"])] = str(entry.get("thread_name") or "")
            self._titles = (modified, titles)
        return self._titles[1].get(ref.session_id, "")
