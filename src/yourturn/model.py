"""Harness-neutral data model shared by every session source."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class Harness(StrEnum):
    CODEX = "codex"
    CLAUDE = "claude"
    CURSOR = "cursor"


class Phase(StrEnum):
    """What the agent is doing."""

    IDLE = "idle"
    WORKING = "working"
    WAITING = "waiting"
    DONE = "done"
    INTERRUPTED = "interrupted"


class Attention(StrEnum):
    """What the user sees: does it need me?"""

    NEEDS_YOU = "needs_you"
    WORKING = "working"
    QUIET = "quiet"
    DONE = "done"


class CheckState(StrEnum):
    """Can I trust it? `NOT_APPLICABLE` covers turns with no edits or only documentation edits."""

    PASSED = "passed"
    FAILED = "failed"
    UNCHECKED = "unchecked"
    NOT_APPLICABLE = "n/a"
    UNKNOWN = "unknown"


class NextKind(StrEnum):
    ANSWER = "answer"
    REVIEW = "review"
    APPROVE = "approve"
    RUN = "run"
    DECIDE = "decide"
    DO = "do"
    NONE = "none"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SessionKey:
    """A session id namespaced by harness, written `harness:native_id`."""

    harness: Harness
    native_id: str

    def __str__(self) -> str:
        return f"{self.harness}:{self.native_id}"

    @classmethod
    def parse(cls, raw: str) -> SessionKey:
        """Split on the first colon only, so composite native ids (`db#id:part`) survive.

        A bare UUID is a Codex thread id, which keeps today's `/api/threads/<uuid>` URLs working.
        """
        if ":" not in raw:
            if not UUID.match(raw):
                raise ValueError(f"not a session key: {raw!r}")
            return cls(Harness.CODEX, raw)
        prefix, native_id = raw.split(":", 1)
        try:
            harness = Harness(prefix)
        except ValueError:
            raise ValueError(f"unknown harness: {prefix!r}") from None
        if not native_id:
            raise ValueError(f"empty session id: {raw!r}")
        return cls(harness, native_id)


@dataclass
class Step:
    at: str
    kind: str
    title: str
    detail: str = ""
    status: str = "done"
    turn: int = 0


@dataclass
class Decision:
    at: str
    source: str
    question: str
    options: list[str] = field(default_factory=list)
    chosen: str | None = None
    reason: str = ""
    turn: int = 0


@dataclass
class Check:
    command: str
    exit_code: int | None
    at: str


@dataclass
class Turn:
    index: int
    started_at: str = ""
    ended_at: str = ""
    status: str = "working"
    prompt: str = ""
    outcome: str = ""
    recap: str = ""
    next_kind: str = "unknown"
    next_text: str = ""
    formatted: bool = False
    files: list[str] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    # Set only by code edits after a check; a README touch-up does not make passed checks stale.
    edited_after_check: bool = False


# --- Phase 2: harness-adapter view model ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SessionRef:
    """Where one session lives. `harness` is a `Harness` value (StrEnum, so plain str works)."""

    harness: str
    session_id: str
    path: Path | None = None
    cwd: str | None = None

    @property
    def key(self) -> SessionKey:
        """The namespaced `harness:native_id` key; raises ValueError for unknown harnesses."""
        return SessionKey(Harness(self.harness), self.session_id)


@dataclass(frozen=True, slots=True)
class Recap:
    """What happened so far, in one glance."""

    headline: str = ""
    last_agent_message: str = ""
    last_user_prompt: str = ""
    turn_count: int = 0
    started_at: datetime | None = None
    updated_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Checks:
    """Verification commands (tests/lint/build) and whether edits went unchecked since."""

    commands: tuple[str, ...] = ()
    passed: int = 0
    failed: int = 0
    last_command: str | None = None
    last_exit_code: int | None = None
    last_at: datetime | None = None
    has_edits: bool = False
    # Code edits happened after the last check ran (docs-only edits should not set this).
    edited_after_check: bool = False

    @property
    def total(self) -> int:
        return self.passed + self.failed

    @property
    def state(self) -> CheckState:
        """Derived trust signal: PASSED ("Checks passed") vs UNCHECKED ("Edits unchecked") etc."""
        if self.last_command is None and not self.commands:
            return CheckState.UNCHECKED if self.has_edits else CheckState.NOT_APPLICABLE
        if self.last_exit_code is None:
            return CheckState.UNKNOWN
        if self.last_exit_code != 0:
            return CheckState.FAILED
        if self.edited_after_check:
            return CheckState.UNCHECKED
        return CheckState.PASSED


@dataclass(frozen=True, slots=True)
class Changes:
    """Files the agent touched."""

    files: tuple[str, ...] = ()
    added: int | None = None
    removed: int | None = None
    last_edit_at: datetime | None = None

    @property
    def file_count(self) -> int:
        return len(self.files)


@dataclass(frozen=True, slots=True)
class WorktreeStatus:
    """Git/worktree facts; every value may be unknown since we never run git mutations."""

    cwd: str | None = None
    branch: str | None = None
    dirty: bool | None = None
    is_worktree: bool | None = None


@dataclass(frozen=True, slots=True)
class NextStep:
    """What the user should do next."""

    kind: NextKind = NextKind.UNKNOWN
    label: str = ""
    reason: str = ""


@dataclass(frozen=True, slots=True)
class Handoff:
    """How to jump into the session."""

    resume_command: str | None = None
    open_path: str | None = None
    open_uri: str | None = None
    terminal_cwd: str | None = None


@dataclass(frozen=True, slots=True)
class Capabilities:
    """What a harness's session source can tell us."""

    can_resume: bool = False
    has_diffs: bool = False
    has_usage: bool = False
    has_tool_calls: bool = False
    has_checks: bool = False
    live_tail: bool = False
    turn_boundaries: bool = False  # The source marks turn start/end (else they are inferred).
    exit_codes: bool = False  # Commands report real exit codes (else only success/failure).
    approval_prompts: bool = False  # The source records tool-approval prompts.
    structured_questions: bool = False  # Questions to the user come with explicit options.


@dataclass(frozen=True, slots=True)
class UsageTotals:
    """Token totals for a session."""

    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    total_tokens: int = 0


@dataclass(frozen=True, slots=True)
class SessionSnapshot:
    """Lightweight row for the list view."""

    ref: SessionRef
    title: str = ""
    phase: Phase = Phase.IDLE
    attention: Attention = Attention.QUIET
    recap: Recap = field(default_factory=Recap)
    checks: Checks = field(default_factory=Checks)
    changes: Changes = field(default_factory=Changes)
    next_step: NextStep = field(default_factory=NextStep)
    updated_at: datetime | None = None
    usage: UsageTotals | None = None


@dataclass(frozen=True, slots=True)
class SessionDetail:
    """Full view: the snapshot plus worktree, handoff, capabilities and a timeline of `Step`s."""

    snapshot: SessionSnapshot
    worktree: WorktreeStatus = field(default_factory=WorktreeStatus)
    handoff: Handoff = field(default_factory=Handoff)
    capabilities: Capabilities = field(default_factory=Capabilities)
    timeline: tuple[Step, ...] = ()
