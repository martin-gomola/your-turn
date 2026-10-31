"""Normalized, harness-agnostic session events and the adapter protocols. No I/O here."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, TypeAlias, runtime_checkable

from yourturn.model import Capabilities, Handoff, SessionRef

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


@dataclass(frozen=True, slots=True, kw_only=True)
class TurnStarted:
    """A new agent turn began."""

    ts: datetime | None = None
    turn_id: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class TurnEnded:
    """An agent turn finished (completed, interrupted, failed...).

    `duration_ms` is the harness-reported duration; None falls back to the turn's start time.
    """

    ts: datetime | None = None
    turn_id: str | None = None
    reason: str | None = None
    duration_ms: float | None = None


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
    """A shell command the agent ran. `exit_code` is None while running or unknown."""

    ts: datetime | None = None
    command: str = ""
    exit_code: int | None = None
    duration_ms: int | None = None
    output_tail: str | None = None


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
    | Usage
)

EVENT_TYPES: tuple[type, ...] = (
    Meta,
    TurnStarted,
    TurnEnded,
    UserMessage,
    AgentMessage,
    CommandRun,
    FilesEdited,
    ToolCall,
    Reasoning,
    ContextCompacted,
    ApprovalPending,
    Usage,
)


@runtime_checkable
class EventCursor(Protocol):
    """Incremental reader over one session source.

    `read_new()` returns only events appended since the previous call and must leave a
    partial trailing line unconsumed (it is picked up once complete). `offset` is the
    position (e.g. byte offset) just past the last fully consumed record.
    """

    @property
    def ref(self) -> SessionRef: ...

    @property
    def offset(self) -> int: ...

    def read_new(self) -> list[Event]: ...

    def reset(self) -> None:
        """Rewind to the start so the next `read_new()` replays everything."""
        ...


@runtime_checkable
class HarnessAdapter(Protocol):
    """One harness (codex, claude, cursor): finds sessions, opens cursors, builds handoffs."""

    name: str
    capabilities: Capabilities

    def discover(self, root: Path | None = None) -> Iterable[SessionRef]:
        """Yield sessions under `root` (or the harness's default location)."""
        ...

    def open(self, ref: SessionRef) -> EventCursor:
        """Return a fresh cursor positioned at the start of the session."""
        ...

    def handoff(self, ref: SessionRef, cwd: str | None) -> Handoff:
        """Describe how to resume / open the session; pure, no process spawning."""
        ...
