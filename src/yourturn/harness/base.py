"""Normalized, harness-agnostic session events and the adapter base classes."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TypeAlias

from yourturn.heuristics import clip
from yourturn.model import Capabilities, Handoff, SessionRef

# --- Names shared by every harness ---------------------------------------------------------------

DECISION_TOOL = "log_decision"
# Synthetic ToolCall name for a question the agent asked the user.
ASK_USER_TOOL = "ask_user"
# Synthetic ToolCall name for a sub-agent being started.
SUBAGENT_TOOL = "subagent"
# `TurnEnded.reason` of a turn that finished normally.
TURN_COMPLETED = "completed"
# Characters of command output kept on a `CommandRun`.
OUTPUT_TAIL = 400


def command_line(command: str) -> str:
    """The short display text of a shell command: its first line, clipped."""
    lines = command.strip().splitlines()
    return clip(lines[0] if lines else "", 120)


class _Stamp(datetime):
    """A parsed timestamp that keeps its source text, so `format_ts` echoes it unchanged."""

    raw = ""


def parse_ts(value: object) -> datetime | None:
    """Parse an ISO timestamp (`...Z`) into an aware UTC datetime; None when absent/bad."""
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


# All events are keyword-only so field order never matters to adapters or tests.


@dataclass(frozen=True, slots=True, kw_only=True)
class Meta:
    """Session header: identity, environment and optional git info."""

    ts: datetime | None = None
    session_id: str | None = None
    title: str | None = None
    cwd: str | None = None
    model: str | None = None
    model_provider: str | None = None
    reasoning_effort: str | None = None
    harness: str | None = None
    originator: str | None = None
    cli_version: str | None = None
    git_branch: str | None = None
    git_commit: str | None = None
    git_repo_url: str | None = None
    subagent: bool | None = None
    parent_id: str | None = None
    # When the agent asks before running things ("never", "on-request"...); "" clears an earlier turn's.
    approval_policy: str | None = None
    # False when the app keeps no record of the chat's messages, so its turns and current state are unknown.
    content_available: bool | None = None
    # The app's own one-line summary of the chat; never the agent's answer.
    summary: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class TurnStarted:
    """A new agent turn began.

    `trigger` is "" for the user's prompt, or what else started it: "task-notification" when a background
    task the agent started finished and the agent carried on, with no prompt from the user.
    """

    ts: datetime | None = None
    turn_id: str | None = None
    trigger: str = ""


# The turn's end was never recorded: neither finished nor stopped, as far as the source says.
END_NOT_RECORDED = "end not recorded"


@dataclass(frozen=True, slots=True, kw_only=True)
class TurnEnded:
    """An agent turn finished (completed, interrupted, failed...).

    `reason` is None or "completed" for a finished turn, END_NOT_RECORDED when the source moved on to a
    new turn without recording how this one ended, and anything else is why it stopped.
    `duration_ms` is the harness-reported duration; None falls back to the turn's start time.
    `last_message` is the harness's own record of the turn's last agent message, "" when it keeps none.
    """

    ts: datetime | None = None
    turn_id: str | None = None
    reason: str | None = None
    duration_ms: float | None = None
    last_message: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class UserMessage:
    """A prompt from the user. Non-empty `answers` ((question, answer) pairs) replies to asked questions."""

    ts: datetime | None = None
    text: str = ""
    answers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class AgentMessage:
    """A message from the agent to the user.

    `phase` is the harness's message phase ("final_answer" marks the turn's answer); None means the
    harness has no phases, so the turn's last plain message is promoted to its answer. `questions`
    are `{"title", "options"}` dicts the agent asked the user in this message.
    """

    ts: datetime | None = None
    text: str = ""
    phase: str | None = None
    questions: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class CommandRun:
    """A shell command the agent ran. `exit_code` is None while running or unknown.

    `command` is the short display text. `full_command` is the whole command, read only to judge checks
    and never shown; "" means the source keeps no more than `command`. `turn_id` is the turn the source
    says ran it, None when it does not say.
    """

    ts: datetime | None = None
    command: str = ""
    full_command: str = ""
    exit_code: int | None = None
    duration_ms: int | None = None
    output_tail: str | None = None
    turn_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class FilesEdited:
    """One edit/patch application touching `paths`. `ok` is None when the outcome is unknown."""

    ts: datetime | None = None
    paths: tuple[str, ...] = ()
    added: int | None = None
    removed: int | None = None
    ok: bool | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolCall:
    """Any other tool invocation (MCP, web search, ...)."""

    ts: datetime | None = None
    name: str = ""
    arguments: str | None = None
    ok: bool | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Reasoning:
    """A reasoning summary from the agent."""

    ts: datetime | None = None
    text: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class ContextCompacted:
    """The harness compacted the conversation context."""

    ts: datetime | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class ApprovalPending:
    """The harness is blocked on the user approving an action (`pending`), or no longer is."""

    ts: datetime | None = None
    pending: bool = True
    text: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class ToolPending:
    """The agent's latest tool call has no result yet (`text` names it); "" once none is outstanding.

    Unlike `ApprovalPending` it does not mean the user is needed: a long command looks the same.
    """

    ts: datetime | None = None
    text: str = ""


@dataclass(frozen=True, slots=True, kw_only=True)
class Usage:
    """Token usage as reported by the harness.

    The int fields are cumulative totals. `total`, when not None, is the raw cumulative counter dict
    and wins over them (an empty dict means no totals in this report). `last` is the latest request's
    counters and `window` the model context window.
    """

    ts: datetime | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    total_tokens: int = 0
    total: dict[str, int] | None = None
    last: dict[str, int] = field(default_factory=dict)
    window: int | None = None
    # Account quota windows (5h, weekly): None when this report has none, [] when the plan reports no windows.
    limits: list[dict[str, Any]] | None = None


Event: TypeAlias = (
    Meta
    | TurnStarted
    | TurnEnded
    | UserMessage
    | AgentMessage
    | CommandRun
    | FilesEdited
    | ToolCall
    | Reasoning
    | ContextCompacted
    | ApprovalPending
    | ToolPending
    | Usage
)


class EventCursor:
    """Incremental reader over one session source; each adapter's cursor subclasses it.

    `read_new()` returns only events appended since the previous call and must leave a
    partial trailing line unconsumed (it is picked up once complete).
    """

    # Bumped whenever the source shrank and the cursor replayed it from the start; the hub then rebuilds the chat.
    truncations: int = 0
    # Bytes `skip_to_tail` left unread at the start, so the oldest turns are missing from the chat.
    skipped_bytes: int = 0

    @property
    def ref(self) -> SessionRef:
        raise NotImplementedError

    def read_new(self) -> list[Event]:
        raise NotImplementedError

    def reset(self) -> None:
        """Rewind to the start so the next `read_new()` replays everything."""
        raise NotImplementedError

    def skip_to_tail(self, max_bytes: int) -> None:
        """Before the first read, start `max_bytes` from the end. Sources with no file to skip ignore it."""


class JsonlCursor(EventCursor):
    """Byte-offset incremental reader over one JSONL session file.

    Each harness subclasses it and supplies `_parse` (line -> record), `_events` (record -> events)
    and `_head_events` (the header replayed when reading starts mid-file).
    """

    def __init__(self, ref: SessionRef) -> None:
        if ref.path is None:
            raise ValueError(f"{type(self).__name__} needs a SessionRef with a path")
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
    def path(self) -> Path:
        return self._path

    def reset(self) -> None:
        self._offset = 0
        self._skip_partial = False
        self._head = []

    def skip_to_tail(self, max_bytes: int) -> None:
        """Before the first read, start `max_bytes` from the end (replaying the header)."""
        try:
            size = self._path.stat().st_size
        except OSError:
            return
        self.seek(max(0, size - max_bytes))

    def seek(self, start: int) -> None:
        """Before the first read, start at byte `start` (replaying the header).

        The first partial line after the seek point is discarded.
        """
        if self._offset != 0 or start <= 0:
            return
        self._offset, self._skip_partial, self.skipped_bytes = start, True, start
        try:
            self._head = self._head_events()
        except (OSError, ValueError, TypeError, AttributeError):
            self._head = []

    def _head_events(self) -> list[Event]:
        """Header events replayed when reading starts mid-file."""
        return []

    def _parse(self, raw: bytes) -> dict[str, Any] | None:
        """One complete line -> record dict, or None when filtered out or malformed."""
        raise NotImplementedError

    def _events(self, record: dict[str, Any]) -> list[Event]:
        raise NotImplementedError

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
            # Line by line: session files can be hundreds of megabytes and must not be loaded whole.
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


class HarnessAdapter:
    """One harness (codex, claude, cursor): finds sessions, opens cursors, builds handoffs.

    Every hook the hub calls is declared here; the defaults suit a session that is one file of its own.
    """

    name: str
    capabilities: Capabilities

    def discover(self, root: Path | None = None) -> Iterable[SessionRef]:
        """Yield sessions under `root` (or the harness's default location)."""
        raise NotImplementedError

    def open(self, ref: SessionRef) -> EventCursor:
        """Return a fresh cursor positioned at the start of the session."""
        raise NotImplementedError

    def handoff(self, ref: SessionRef, cwd: str | None) -> Handoff:
        """Describe how to resume / open the session; pure, no process spawning."""
        raise NotImplementedError

    def title(self, ref: SessionRef) -> str:
        """The app's own chat title; "" keeps the title the session itself carries."""
        return ""

    def project(self, ref: SessionRef) -> str:
        """The project name shown on the row: the working folder's name unless the app knows better."""
        return Path(ref.cwd).name if ref.cwd else ""

    def mtime_ns(self, ref: SessionRef) -> int | None:
        """When the session last changed (None once it is gone): its file's modification time."""
        if ref.path is None:
            return None
        try:
            return ref.path.stat().st_mtime_ns
        except OSError:
            return None

    def state_token(self, ref: SessionRef) -> str:
        """Changes when session state kept outside its file changes (Cursor approvals); "" when there is none."""
        return ""
