"""Session engine: fold a session's history into one state, and serve it as typed views or API dicts.

`TurnFolder` is the single state machine (no I/O): every state change goes through
`fold(event)` on normalized harness `Event`s. `feed(record)` only maps a raw Codex rollout record
through `record_to_events` and folds the result.

`SessionHub` owns every per-session state the app serves, reading every source through its
adapter's cursor (`adapter.open(ref).read_new()` -> `fold`): the `refresh()` view and,
when built with a `CodexCatalog`, the inbox rows, the per-thread detail state and the stream
fingerprint (`inbox_dicts`, `detail_dict`, `inbox_fingerprint`). No threads of its own: the
caller drives reads, and one lock serializes request threads and the event stream.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from collections import OrderedDict, deque
from collections.abc import Iterable, Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from yourturn.config import DEFAULT_HISTORY_DAYS
from yourturn.harness.base import (
    AgentMessage,
    ApprovalPending,
    CommandRun,
    ContextCompacted,
    Event,
    EventCursor,
    FilesEdited,
    HarnessAdapter,
    Meta,
    Reasoning,
    ToolCall,
    TurnEnded,
    TurnStarted,
    Usage,
    UserMessage,
)
from yourturn.harness.codex import (
    ASK_USER_TOOL,
    DECISION_TOOL,
    ROLLOUT_GLOB,
    SUBAGENT_TOOL,
    TURN_COMPLETED,
    CodexAdapter,
    format_ts,
    is_background,
    parse_ts,
    record_to_events,
    thread_id_of,
)
from yourturn.harness.claude import ClaudeAdapter
from yourturn.harness.cursor import CursorAdapter
from yourturn.heuristics import (
    check_key,
    check_state,
    clip,
    code_paths,
    is_check_command,
    is_quiet,
    needs_you,
    parse_answer,
    parse_recap,
)
from yourturn.model import (
    UUID,
    Attention,
    Capabilities,
    Changes,
    Check,
    Checks,
    Decision,
    Handoff,
    Harness,
    NextKind,
    NextStep,
    Phase,
    Recap,
    SessionDetail,
    SessionKey,
    SessionRef,
    SessionSnapshot,
    Step,
    Turn,
    UsageTotals,
    WorktreeStatus,
)

MAX_STEPS = 300
MAX_TURNS = 30
MAX_DETAILS = 16
DEFAULT_TAIL_BYTES = 8 * 1024 * 1024
INBOX_TAIL_BYTES = DEFAULT_TAIL_BYTES
ASK_TOOLS = frozenset({ASK_USER_TOOL})


def _ns(value: datetime | None) -> int:
    return int(value.timestamp() * 1e9) if value is not None else 0


def _parse(text: str) -> datetime | None:
    try:
        return parse_ts(text)
    except (TypeError, ValueError):
        return None


def iso(epoch: float) -> str:
    """Second-precision UTC timestamp, the inbox `updated_at` format."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


class TurnFolder:
    """Folds one session's history (in order) into turns, checks, decisions, steps and usage.

    Attribute names match the old `rollout.ThreadState`, so `Sessions.state()` callers keep working;
    `started_at` / `updated_at` are the raw timestamp strings the API returns.
    """

    def __init__(self, ref: SessionRef) -> None:
        self.ref = ref
        self.title = ""
        self.project = ""
        self.cwd: str = ref.cwd or ""
        self.parent_id = ""
        self.subagent = False
        self.started_at = ""
        self.updated_at = ""
        self.status = "idle"
        self.context_used = 0
        self.context_window = 0
        self.token_usage: dict[str, int] = {}
        self.last_token_usage: dict[str, int] = {}
        self.token_usage_at = ""
        self.model = ""
        self.reasoning_effort = ""
        self.model_provider = ""
        self.git_branch = ""
        self.cli_version = ""
        self.activity = ""
        self.attention_key = ""
        self.version = 0
        self.turns: deque[Turn] = deque(maxlen=MAX_TURNS)
        self.steps: deque[Step] = deque(maxlen=MAX_STEPS)
        self.decisions: list[Decision] = []
        self.usage: UsageTotals | None = None
        self._started_ts: datetime | None = None
        self._updated_ts: datetime | None = None
        self._last_message: tuple[int, str, str, Step] | None = None  # (turn, at, text, step)
        self._last_agent_text = ""
        self._last_edit_at: datetime | None = None
        # A pending approval overlays the latest turn's state until the harness clears it.
        self.approval = ""
        self._attention_before = ""

    @property
    def id(self) -> str:
        return self.ref.session_id

    # -- shared folding rules ----------------------------------------------------------------------

    def _turn(self, at: str) -> Turn:
        """The current turn; created lazily when reading starts mid-turn (tail reads)."""
        if not self.turns:
            self.turns.append(Turn(index=0, started_at=at))
            self.status = "working"
        return self.turns[-1]

    def _step(self, at: str, kind: str, title: str, detail: str = "", status: str = "done") -> Step:
        step = Step(at, kind, clip(title), clip(detail), status, self._turn(at).index)
        self.steps.append(step)
        if kind not in {"turn", "user"}:
            self.activity = clip(title, 120)
        return step

    def _pending(self) -> list[Decision]:
        return [d for d in self.decisions if d.source == "asked" and d.chosen is None]

    def _attention(self, at: str, kind: str, content: object) -> None:
        # Event identity survives tail reads; usage updates and file mtimes do not identify a new request.
        value = json.dumps([self.ref.session_id, at, kind, content], sort_keys=True, ensure_ascii=False)
        self.attention_key = hashlib.sha256(value.encode()).hexdigest() if at else ""

    def _turn_started(self, at: str) -> None:
        self.attention_key = ""
        if self.turns and not self.turns[-1].ended_at:
            self.turns[-1].ended_at, self.turns[-1].status = at, "interrupted"
        index = self.turns[-1].index + 1 if self.turns else 1
        self.turns.append(Turn(index=index, started_at=at))
        self._last_message = None
        self.status = "working"
        self._step(at, "turn", f"Turn {index} started")

    def _close_turn(self, at: str, stopped: str | None, duration: str) -> None:
        """End the current turn: `stopped` is the abort reason, or None for a completed turn."""
        turn = self._turn(at)
        turn.ended_at = at
        if stopped is not None:
            turn.status = "interrupted"
            self._step(at, "turn", f"Turn {turn.index} stopped", stopped, "failed")
        else:
            pending = [d for d in self._pending() if d.turn == turn.index]
            turn.status = "waiting" if pending else "done"
            if pending and turn.next_kind in ("unknown", "none"):
                turn.next_kind, turn.next_text = "answer", pending[0].question
            self._step(at, "turn", f"Turn {turn.index} finished", duration)
        self.status = turn.status

    def _apply_answer(self, turn: Turn, at: str, text: str) -> None:
        turn.outcome, turn.next_kind, turn.next_text, turn.formatted = parse_answer(text)
        turn.recap = parse_recap(text)
        self.attention_key = ""
        if turn.next_kind not in {"unknown", "none"} and turn.next_text:
            self._attention(at, turn.next_kind, text)

    def _prompt(self, at: str, turn: Turn, text: str) -> None:
        for decision in self._pending():
            decision.chosen = clip(text, 120)
        turn.prompt = turn.prompt or clip(text, 160)
        self._step(at, "user", "You", text)

    def _run(self, at: str, turn: Turn, command: str, exit_code: Any) -> None:
        failed = exit_code not in (0, None)
        if is_check_command(command):
            # `cd repo && pytest` and `pytest` are the same check; a later run replaces the earlier result.
            key = check_key(command)
            turn.checks = [check for check in turn.checks if check_key(check.command) != key]
            turn.checks.append(Check(command, exit_code, at))
            turn.edited_after_check = False
        self._step(at, "command", command, f"exit {exit_code}" if failed else "", "failed" if failed else "done")

    def _edit(self, at: str, turn: Turn, paths: list[str], ts: datetime | None, failed: bool) -> None:
        turn.files.extend(path for path in paths if path not in turn.files)
        # Documentation edits after a passing check do not make it stale.
        turn.edited_after_check = turn.edited_after_check or (bool(turn.checks) and bool(code_paths(paths)))
        self._last_edit_at = ts or self._last_edit_at
        noun = "file" if len(paths) == 1 else "files"
        self._step(at, "edit", f"Edited {len(paths)} {noun}", ", ".join(Path(p).name for p in paths), "failed" if failed else "done")

    def _ask(self, at: str, turn: Turn, question: dict[str, Any]) -> None:
        self._attention(at, "question", question)
        options = [str(option) for option in question.get("options") or []]
        title = clip(str(question.get("title", "")))
        self.decisions.append(Decision(at, "asked", title, options, turn=turn.index))
        self._step(at, "question", title, " · ".join(options), "waiting")
        # Asking blocks the agent until the user answers, even inside a turn (Claude Code).
        self.status = "waiting"

    def _decide(self, at: str, turn: Turn, args: Any) -> None:
        options = [str(option) for option in args.get("options") or []]
        decision = Decision(
            at,
            "agent",
            clip(str(args.get("question", ""))),
            options,
            clip(str(args.get("chosen", "")), 120),
            clip(str(args.get("reason", ""))),
            turn.index,
        )
        self.decisions.append(decision)
        self._step(at, "decision", decision.question, f"Chose {decision.chosen}")

    # -- normalized events -------------------------------------------------------------------------

    def fold_many(self, events: Iterable[Event]) -> None:
        for event in events:
            self.fold(event)

    def fold(self, event: Event) -> None:
        self.version += 1
        ts = event.ts
        at = format_ts(ts)
        if ts is not None and (self._updated_ts is None or ts >= self._updated_ts):
            self._updated_ts, self.updated_at = ts, at
        if isinstance(event, Meta):
            self._meta(event)
        elif isinstance(event, TurnStarted):
            self._turn_started(at)
        elif isinstance(event, TurnEnded):
            self._turn_ended(at, event)
        elif isinstance(event, Usage):
            self._usage(at, event)
        elif isinstance(event, UserMessage):
            self._user(at, event)
        elif isinstance(event, AgentMessage):
            self._agent(at, event)
        elif isinstance(event, Reasoning):
            self._turn(at)
            if event.text:
                self._step(at, "thinking", event.text)
        elif isinstance(event, ContextCompacted):
            self._step(at, "turn", "Context compacted")
        elif isinstance(event, ApprovalPending):
            self._approval(at, event)
        elif isinstance(event, CommandRun):
            self._run(at, self._turn(at), event.command, event.exit_code)
        elif isinstance(event, FilesEdited):
            self._edit(at, self._turn(at), list(event.paths), event.ts, event.ok is False)
        elif isinstance(event, ToolCall):
            self._tool(at, event)

    def _meta(self, event: Meta) -> None:
        if event.title:
            self.title = event.title
        if event.cwd is not None:
            self.cwd = event.cwd
        if event.model is not None:
            self.model = event.model
        if event.git_branch is not None:
            self.git_branch = event.git_branch
        if event.cli_version is not None:
            self.cli_version = event.cli_version
        if event.model_provider is not None:
            self.model_provider = event.model_provider
        if event.reasoning_effort is not None:
            self.reasoning_effort = event.reasoning_effort
        if event.subagent is not None:
            self.subagent = event.subagent
        if event.parent_id is not None:
            self.parent_id = event.parent_id
        # Only the session header carries cwd; turn_context Meta events carry just the model.
        if event.cwd is not None and event.ts is not None:
            self._started_ts, self.started_at = event.ts, format_ts(event.ts)

    def _turn_ended(self, at: str, event: TurnEnded) -> None:
        if event.reason not in (TURN_COMPLETED, None):
            self._close_turn(at, str(event.reason), "")
            return
        turn = self._turn(at)
        self._final_answer(turn)
        if event.duration_ms is not None:
            seconds = round(event.duration_ms / 1000)
        else:
            started = parse_ts(turn.started_at)
            seconds = round((event.ts - started).total_seconds()) if started and event.ts else 0
        self._close_turn(at, None, f"{seconds}s" if seconds > 0 else "")

    def _final_answer(self, turn: Turn) -> None:
        """Without message phases, the turn's last plain agent message is its final answer."""
        if self._last_message is None or self._last_message[0] != turn.index:
            return
        _, at, text, step = self._last_message
        self._apply_answer(turn, at, text)
        step.kind, step.title = "answer", clip(turn.outcome or text)
        self._last_message = None

    def _agent(self, at: str, event: AgentMessage) -> None:
        turn, text = self._turn(at), event.text
        if text:
            self._last_agent_text = text
        if event.phase == "final_answer":
            self._apply_answer(turn, at, text)
            self._step(at, "answer", turn.outcome or text)
            self._last_message = None
        else:
            step = self._step(at, "message", text)
            # A message that asks questions waits for answers; it is not the turn's answer.
            if event.phase is None and not event.questions:
                self._last_message = (turn.index, at, text, step)
        for question in event.questions:
            self._ask(at, turn, question)

    def _user(self, at: str, event: UserMessage) -> None:
        turn = self._turn(at)
        if event.answers:
            self._answers(at, turn, event.answers)
        elif event.text:
            self._prompt(at, turn, event.text)

    def _answers(self, at: str, turn: Turn, answers: tuple[tuple[str, str], ...]) -> None:
        pending = self._pending()
        for question, answer in answers:
            decision = next((d for d in pending if d.question == question), pending[0] if pending else None)
            if decision is not None:
                decision.chosen = answer
                pending.remove(decision)
            turn.prompt = turn.prompt or f"Answered: {answer}"
            self._step(at, "user", f"You answered: {answer}", question)
        if self.status == "waiting" and not self._pending():
            self.status = "working"

    def _approval(self, at: str, event: ApprovalPending) -> None:
        if event.pending and not self.approval:
            self.approval = clip(event.text, 160) or "Approve the pending action"
            self._attention_before = self.attention_key
            self._attention(at, "approve", self.approval)
            self._step(at, "question", self.approval, status="waiting")
        elif not event.pending and self.approval:
            self.approval = ""
            self.attention_key = self._attention_before

    def _status(self) -> str:
        return "waiting" if self.approval else self.status

    def _next(self, turn: Turn | None) -> tuple[str, str]:
        if self.approval:
            return "approve", self.approval
        return (turn.next_kind, turn.next_text) if turn else ("unknown", "")

    def _usage(self, at: str, event: Usage) -> None:
        total = (
            dict(event.total)
            if event.total is not None
            else {
                "input_tokens": event.input_tokens,
                "cached_input_tokens": event.cached_input_tokens,
                "output_tokens": event.output_tokens,
                "total_tokens": event.total_tokens,
            }
        )
        if total:
            self.token_usage, self.token_usage_at = total, at
            self.usage = UsageTotals(
                input_tokens=total.get("input_tokens", 0),
                output_tokens=total.get("output_tokens", 0),
                cached_input_tokens=total.get("cached_input_tokens", 0),
                total_tokens=total.get("total_tokens", 0),
            )
        if event.last:
            self.last_token_usage = dict(event.last)
            if "total_tokens" in event.last:
                self.context_used = event.last["total_tokens"]
        if event.window is not None:
            self.context_window = event.window

    def _tool(self, at: str, event: ToolCall) -> None:
        turn = self._turn(at)
        args = _json_object(event.arguments)
        if event.name in ASK_TOOLS:
            self._ask(at, turn, args)
        elif event.name == DECISION_TOOL:
            self._decide(at, turn, args)
        elif event.name == SUBAGENT_TOOL:
            self._step(at, "agent", f"Sub-agent started: {event.arguments}")
        else:
            self._step(at, "tool", event.name, status="failed" if event.ok is False else "done")

    # -- raw Codex rollout records -----------------------------------------------------------------

    def feed(self, record: dict[str, Any]) -> None:
        """Fold one raw Codex rollout record; feed records in file order."""
        self.fold_many(record_to_events(record))

    # -- API dicts (the JSON contract app.js reads) -------------------------------------------------

    def inbox_fields(self, mtime_ns: int | None = None) -> dict[str, Any]:
        """The file-content part of an inbox row; `needs_you` is judged on exactly these keys."""
        turn = self.turns[-1] if self.turns else None
        pending = next((d for d in reversed(self.decisions) if d.source == "asked" and d.chosen is None), None)
        next_kind, next_text = self._next(turn)
        row: dict[str, Any] = {
            "id": self.id,
            "cwd": self.cwd,
            "status": self._status(),
            "updated_at": iso(mtime_ns / 1e9) if mtime_ns is not None else self.updated_at,
            "turn_ended_at": turn.ended_at if turn else "",
            "outcome": turn.outcome if turn else "",
            "next_kind": next_kind,
            "next_text": next_text,
            "question": pending.question if pending else "",
            "options": pending.options if pending else [],
            "attention_key": self.attention_key,
            "check_state": check_state(turn),
        }
        row["needs_you"] = needs_you(row)
        return row

    def inbox_row(self, mtime_ns: int | None = None) -> dict[str, Any]:
        """A full inbox row: `inbox_fields` plus `quiet`, `project` and `title`."""
        row = self.inbox_fields(mtime_ns)
        row["quiet"] = is_quiet(self._status(), mtime_ns if mtime_ns is not None else _ns(self._updated_ts))
        row["project"] = self.project
        row["title"] = self.title
        return row

    def to_dict(self) -> dict[str, Any]:
        """The thread view (`/api/threads/<id>` minus `quiet`)."""
        turns = [asdict(turn) for turn in self.turns]
        if turns and self.approval:
            turns[-1]["next_kind"], turns[-1]["next_text"] = self._next(None)
        last = turns[-1] if turns else {"next_kind": "unknown", "next_text": ""}
        return {
            "id": self.id,
            "title": self.title,
            "cwd": self.cwd,
            "project": self.project,
            "parent_id": self.parent_id,
            "subagent": self.subagent,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "status": self._status(),
            "context_used": self.context_used,
            "context_window": self.context_window,
            "token_usage": dict(self.token_usage),
            "last_token_usage": dict(self.last_token_usage),
            "token_usage_at": self.token_usage_at,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort,
            "model_provider": self.model_provider,
            "git_branch": self.git_branch,
            "cli_version": self.cli_version,
            "activity": self.activity,
            "attention_key": self.attention_key,
            "version": self.version,
            "turns": turns,
            "steps": [asdict(step) for step in self.steps],
            "decisions": [asdict(decision) for decision in self.decisions],
            "needs_you": needs_you({**last, "status": self._status()}),
        }

    # -- typed views -------------------------------------------------------------------------------

    def snapshot(self, mtime_ns: int | None = None) -> SessionSnapshot:
        turn = self.turns[-1] if self.turns else None
        row = self.inbox_row(mtime_ns)
        if row["needs_you"]:
            attention = Attention.NEEDS_YOU
        elif self.status == "working":
            attention = Attention.QUIET if row["quiet"] else Attention.WORKING
        elif self.status in ("done", "interrupted"):
            attention = Attention.DONE
        else:
            attention = Attention.QUIET
        try:
            phase = Phase(self._status())
        except ValueError:
            phase = Phase.IDLE
        return SessionSnapshot(
            ref=self.ref,
            title=self.title or self._first_prompt(),
            phase=phase,
            attention=attention,
            recap=self._recap(turn),
            checks=self._checks(turn),
            changes=self._changes(turn),
            next_step=self._next_step(turn, row),
            updated_at=self._updated_ts,
            usage=self.usage,
        )

    def detail(
        self,
        mtime_ns: int | None = None,
        handoff: Handoff | None = None,
        capabilities: Capabilities | None = None,
    ) -> SessionDetail:
        return SessionDetail(
            snapshot=self.snapshot(mtime_ns),
            worktree=WorktreeStatus(cwd=self.cwd or None, branch=self.git_branch or None),
            handoff=handoff or Handoff(),
            capabilities=capabilities or Capabilities(),
            timeline=tuple(self.steps),
        )

    def _first_prompt(self) -> str:
        return next((clip(turn.prompt, 80) for turn in self.turns if turn.prompt), "")

    def _recap(self, turn: Turn | None) -> Recap:
        prompt = next((t.prompt for t in reversed(self.turns) if t.prompt), "")
        return Recap(
            headline=(turn.recap or turn.outcome) if turn else "",
            last_agent_message=clip(self._last_agent_text, 160),
            last_user_prompt=prompt,
            turn_count=sum(1 for t in self.turns if t.index > 0),
            started_at=self._started_ts or (_parse(self.turns[0].started_at) if self.turns else None),
            updated_at=self._updated_ts,
        )

    def _checks(self, turn: Turn | None) -> Checks:
        if turn is None:
            return Checks()
        last = turn.checks[-1] if turn.checks else None
        return Checks(
            commands=tuple(check.command for check in turn.checks),
            passed=sum(1 for check in turn.checks if check.exit_code == 0),
            failed=sum(1 for check in turn.checks if check.exit_code not in (0, None)),
            last_command=last.command if last else None,
            last_exit_code=last.exit_code if last else None,
            last_at=_parse(last.at) if last else None,
            has_edits=bool(code_paths(turn.files)),
            edited_after_check=turn.edited_after_check,
        )

    def _changes(self, turn: Turn | None) -> Changes:
        if turn is None:
            return Changes()
        return Changes(files=tuple(turn.files), last_edit_at=self._last_edit_at if turn.files else None)

    def _next_step(self, turn: Turn | None, row: dict[str, Any]) -> NextStep:
        if turn is None:
            return NextStep()
        try:
            kind = NextKind(row["next_kind"])
        except ValueError:
            kind = NextKind.UNKNOWN
        reason = "The agent asked a question" if row["question"] else "The agent is waiting for approval" if self.approval else turn.outcome
        return NextStep(kind=kind, label=row["next_text"], reason=reason)


def _json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


# --- Codex rollout files -------------------------------------------------------------------------


class RolloutParser:
    """Raw Codex record entry point: `feed(record)` folds into `state` (a `TurnFolder`)."""

    def __init__(self, thread_id: str, ref: SessionRef | None = None) -> None:
        self.state = TurnFolder(ref or SessionRef(harness=Harness.CODEX.value, session_id=thread_id))

    def feed(self, record: dict[str, Any]) -> None:
        self.state.feed(record)


class RolloutTail:
    """Follows one rollout file through `CodexAdapter.open()`; each read folds only appended records."""

    def __init__(
        self,
        path: Path,
        thread_id: str,
        start: int = 0,
        ref: SessionRef | None = None,
        adapter: CodexAdapter | None = None,
    ) -> None:
        self.ref = ref if ref is not None and ref.path == path else SessionRef(
            harness=Harness.CODEX.value, session_id=thread_id, path=path, cwd=ref.cwd if ref else None
        )
        self.cursor = (adapter or CodexAdapter()).open(self.ref)
        self.cursor.seek(start)
        self.state = TurnFolder(self.ref)
        self._truncations = self.cursor.truncations

    @property
    def path(self) -> Path:
        return self.cursor.path

    def read(self) -> TurnFolder:
        self.path.stat()  # A vanished file raises OSError, which callers treat as archived.
        events = self.cursor.read_new()
        if self.cursor.truncations != self._truncations:
            # Rewritten shorter: the cursor replayed from the start, so rebuild state.
            self._truncations = self.cursor.truncations
            self.state = TurnFolder(self.ref)
        self.state.fold_many(events)
        return self.state


class CodexCatalog:
    """Locates rollout files, chat titles and project names under a Codex home directory."""

    def __init__(self, codex_home: Path, scan_ttl: float = 3.0) -> None:
        self.root = codex_home / "sessions"
        self.index = codex_home / "session_index.jsonl"
        self.scan_ttl = scan_ttl
        self._scan: tuple[float, list[Path]] = (0.0, [])
        self._titles: tuple[float, dict[str, str]] = (-1.0, {})
        self._subagent: dict[Path, bool] = {}
        self._project_db_mtime = -1
        self._project_roots: list[tuple[str, str]] = []

    def project_name(self, cwd: str) -> str:
        """Match a chat's working directory to Codex's saved project roots when available."""
        state_db = self.root.parent / "state_5.sqlite"
        try:
            modified = state_db.stat().st_mtime_ns
        except OSError:
            return Path(cwd).name
        if modified != self._project_db_mtime:
            self._project_roots = []
            try:
                connection = sqlite3.connect(f"{state_db.as_uri()}?mode=ro")
                try:
                    self._project_roots = sorted(
                        ((root, name) for root, name in connection.execute(
                            "SELECT project_roots.path, projects.name FROM project_roots "
                            "JOIN projects ON projects.id = project_roots.project_id"
                        ) if root and name),
                        key=lambda item: len(item[0]), reverse=True,
                    )
                finally:
                    connection.close()
            except sqlite3.Error:
                pass
            self._project_db_mtime = modified
        for root, name in self._project_roots:
            root = root.rstrip("/")
            if cwd == root or cwd.startswith(root + "/"):
                return name
        return Path(cwd).name

    def rollouts(self) -> list[Path]:
        """All rollout files, newest modification first; cached briefly because there can be thousands."""
        scanned_at, paths = self._scan
        if time.monotonic() - scanned_at > self.scan_ttl:
            found = []
            for path in self.root.glob(ROLLOUT_GLOB):
                try:
                    found.append((path.stat().st_mtime, path))
                except OSError:
                    continue
            paths = [path for _, path in sorted(found, reverse=True)]
            self._scan = (time.monotonic(), paths)
        return paths

    def is_subagent(self, path: Path) -> bool:
        """Sub-agent threads and `codex exec` runs get their own rollout file; session_meta on the first line says so."""
        if path not in self._subagent:
            try:
                with path.open("rb") as handle:
                    meta = json.loads(handle.readline())
                source = meta.get("payload", {}).get("source")
                self._subagent[path] = is_background(source)
            except (OSError, ValueError, AttributeError):
                self._subagent[path] = False
        return self._subagent[path]

    def chats(self, history_days: int = DEFAULT_HISTORY_DAYS) -> list[Path]:
        """Newest user-facing chats, skipping sub-agent threads."""
        chats: list[Path] = []
        cutoff = time.time() - history_days * 86400
        for path in self.rollouts():
            try:
                if path.stat().st_mtime < cutoff:
                    break
            except OSError:
                continue
            if not self.is_subagent(path):
                chats.append(path)
        return chats

    def find(self, thread_id: str) -> Path | None:
        if not UUID.match(thread_id):
            return None
        for path in self.rollouts():
            if thread_id_of(path) == thread_id:
                return path
        # A chat started since the last cached scan.
        return next(self.root.glob(f"*/*/*/rollout-*-{thread_id}.jsonl"), None)

    def titles(self) -> dict[str, str]:
        try:
            modified = self.index.stat().st_mtime
        except OSError:
            return {}
        if modified != self._titles[0]:
            titles: dict[str, str] = {}
            for line in self.index.read_text(encoding="utf-8", errors="replace").splitlines():
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(entry, dict) and entry.get("id"):
                    titles[str(entry["id"])] = str(entry.get("thread_name") or "")
            self._titles = (modified, titles)
        return self._titles[1]


# --- Hub -----------------------------------------------------------------------------------------


class _Tracked:
    __slots__ = ("adapter", "ref", "cursor", "folder", "truncations")

    def __init__(self, adapter: HarnessAdapter, ref: SessionRef, cursor: EventCursor, folder: TurnFolder) -> None:
        self.adapter = adapter
        self.ref = ref
        self.cursor = cursor
        self.folder = folder
        self.truncations = int(getattr(cursor, "truncations", 0))


def _keyed(row: dict[str, Any], adapter: HarnessAdapter | None, ref: SessionRef) -> dict[str, Any]:
    """Add the harness, the full `<harness>:<native_id>` key and the adapter's handoff to an API dict."""
    row["harness"] = ref.harness
    row["key"] = str(ref.key)
    row["handoff"] = asdict(adapter.handoff(ref, row.get("cwd") or None)) if adapter else asdict(Handoff())
    return row


class SessionHub:
    """Owns every session state the app serves.

    Adapter mode (`refresh` / `snapshots` / `detail`): one adapter cursor + `TurnFolder` per
    discovered session, folding only newly appended events.

    Catalog mode (`catalog=` or `for_codex_home`): the API dicts. Inbox rows come from a tail read
    (last `tail_bytes`) cached per file signature; thread detail comes from a full incremental read
    kept for the `max_details` most recently viewed threads.
    """

    def __init__(
        self,
        adapters: Sequence[HarnessAdapter] | None = None,
        *,
        root: Path | None = None,
        tail_bytes: int | None = DEFAULT_TAIL_BYTES,
        rescan_seconds: float = 3.0,
        catalog: CodexCatalog | None = None,
        max_details: int = MAX_DETAILS,
    ) -> None:
        self.adapters: list[HarnessAdapter] = (
            list(adapters)
            if adapters is not None
            else [
                CodexAdapter(max_age_days=DEFAULT_HISTORY_DAYS),
                ClaudeAdapter(max_age_days=DEFAULT_HISTORY_DAYS),
                CursorAdapter(max_age_days=DEFAULT_HISTORY_DAYS),
            ]
        )
        self.root = root
        self.tail_bytes = tail_bytes
        self.rescan_seconds = rescan_seconds
        self.catalog = catalog
        self.max_details = max_details
        self._tracked: dict[SessionKey, _Tracked] = {}
        self._scanned_at: float | None = None
        self._inbox: dict[Path, tuple[tuple[int, int], dict[str, Any]]] = {}
        self._details: OrderedDict[str, RolloutTail] = OrderedDict()
        # Request threads and the event stream share these caches and tails.
        self._lock = threading.RLock()

    @classmethod
    def for_codex_home(
        cls,
        codex_home: Path,
        *,
        scan_ttl: float = 3.0,
        claude_home: Path | None = None,
        cursor_home: Path | None = None,
        cursor_user_dir: Path | None = None,
    ) -> SessionHub:
        """Codex catalog hub; `claude_home` / `cursor_home` also register those harnesses' sessions."""
        adapters: list[HarnessAdapter] = [CodexAdapter(home=codex_home)]
        if claude_home is not None:
            adapters.append(ClaudeAdapter(home=claude_home))
        if cursor_home is not None:
            adapters.append(CursorAdapter(home=cursor_home, user_dir=cursor_user_dir))
        return cls(
            adapters,
            root=codex_home,
            tail_bytes=INBOX_TAIL_BYTES,
            rescan_seconds=scan_ttl,
            catalog=CodexCatalog(codex_home, scan_ttl),
        )

    # -- adapter mode ------------------------------------------------------------------------------

    def _discover(self) -> None:
        now = time.monotonic()
        if self._scanned_at is not None and now - self._scanned_at < self.rescan_seconds:
            return
        seen: set[SessionKey] = set()
        for adapter in self._tracked_adapters():
            try:
                refs = list(adapter.discover(self.root))
            except OSError:
                continue
            for ref in refs:
                try:
                    key = ref.key
                except ValueError:
                    continue
                seen.add(key)
                tracked = self._tracked.get(key)
                if tracked is None or tracked.ref.path != ref.path:
                    self._tracked[key] = self._track(adapter, ref)
        for stale in set(self._tracked) - seen:
            del self._tracked[stale]
        self._scanned_at = now

    def _tracked_adapters(self) -> list[HarnessAdapter]:
        # With a catalog, Codex sessions are served by it (tail-cached inbox rows); track the rest.
        if self.catalog is None:
            return self.adapters
        return [adapter for adapter in self.adapters if not isinstance(adapter, CodexAdapter)]

    def _track(self, adapter: HarnessAdapter, ref: SessionRef) -> _Tracked:
        cursor = adapter.open(ref)
        skip = getattr(cursor, "skip_to_tail", None)
        if self.tail_bytes is not None and callable(skip):
            skip(self.tail_bytes)
        return _Tracked(adapter, ref, cursor, TurnFolder(ref))

    def _pump(self, tracked: _Tracked) -> None:
        events = tracked.cursor.read_new()
        truncations = int(getattr(tracked.cursor, "truncations", 0))
        if truncations != tracked.truncations:
            # The file shrank and the cursor replayed from the start: rebuild state.
            tracked.truncations = truncations
            tracked.folder = TurnFolder(tracked.ref)
        if events:
            tracked.folder.fold_many(events)
        project_of = getattr(tracked.adapter, "project", None)
        if callable(project_of) and not tracked.folder.project:
            tracked.folder.project = project_of(tracked.ref)
        title_of = getattr(tracked.adapter, "title", None)
        if callable(title_of):
            title = title_of(tracked.ref)
            if title:
                tracked.folder.title = title

    @staticmethod
    def _path_mtime(path: Path | None) -> int | None:
        if path is None:
            return None
        try:
            return path.stat().st_mtime_ns
        except OSError:
            return None

    @classmethod
    def _mtime_ns(cls, tracked: _Tracked) -> int | None:
        return cls._path_mtime(tracked.ref.path)

    def refresh(self) -> list[SessionSnapshot]:
        with self._lock:
            self._discover()
            for tracked in self._tracked.values():
                self._pump(tracked)
            return self.snapshots()

    def snapshots(self) -> list[SessionSnapshot]:
        rows = [tracked.folder.snapshot(self._mtime_ns(tracked)) for tracked in self._tracked.values()]
        rows.sort(key=lambda row: row.updated_at.timestamp() if row.updated_at else 0.0, reverse=True)
        return rows

    def detail(self, key: SessionKey | str) -> SessionDetail | None:
        key = _parse_key(key)
        if key is None:
            return None
        if self.catalog is not None and key.harness is Harness.CODEX:
            with self._lock:
                folder = self._read_state(key.native_id)
                if folder is None:
                    return None
                path = self._details[key.native_id].path
                adapter = self._codex()
                ref = SessionRef(harness=Harness.CODEX.value, session_id=key.native_id, path=path, cwd=folder.cwd or None)
                return folder.detail(
                    self._path_mtime(path),
                    handoff=adapter.handoff(ref, folder.cwd or None) if adapter else None,
                    capabilities=adapter.capabilities if adapter else None,
                )
        tracked = self._tracked.get(key)
        if tracked is None:
            return None
        folder = tracked.folder
        return folder.detail(
            self._mtime_ns(tracked),
            handoff=tracked.adapter.handoff(tracked.ref, folder.cwd or None),
            capabilities=tracked.adapter.capabilities,
        )

    # -- catalog mode: the API dicts ---------------------------------------------------------------

    def _codex(self) -> CodexAdapter | None:
        return next((a for a in self.adapters if isinstance(a, CodexAdapter)), None)

    def _require_catalog(self) -> CodexCatalog:
        if self.catalog is None:
            raise RuntimeError("SessionHub was built without a CodexCatalog")
        return self.catalog

    def find(self, thread_id: str) -> Path | None:
        with self._lock:
            return self._require_catalog().find(thread_id)

    def inbox_dicts(self, history_days: int = DEFAULT_HISTORY_DAYS, *, tail_bytes: int | None = None) -> list[dict[str, Any]]:
        """One row per user-facing chat in the window, newest file first, parsed from each file's tail.

        `tail_bytes` overrides the hub's `tail_bytes` for files (re)parsed by this call.
        """
        catalog = self._require_catalog()
        limit = self.tail_bytes if tail_bytes is None else tail_bytes
        with self._lock:
            titles = catalog.titles()
            chats = catalog.chats(history_days)
            rows = [row for path in chats if (row := self._inbox_row(catalog, path, titles, limit))]
            for stale in set(self._inbox) - set(chats):
                del self._inbox[stale]
            rows += [self._other_row(tracked) for tracked in self._others(history_days, pump=True)]
            # Stable: Codex rows keep their newest-file-first order among equal timestamps.
            rows.sort(key=lambda row: row["updated_at"], reverse=True)
            return rows

    def _others(self, history_days: int, *, pump: bool) -> list[_Tracked]:
        """Non-Codex sessions written to within the history window, read up to date when `pump`."""
        self._discover()
        cutoff = (time.time() - history_days * 86400) * 1e9
        recent = [tracked for tracked in self._tracked.values() if (self._mtime_ns(tracked) or 0) >= cutoff]
        if pump:
            for tracked in recent:
                self._pump(tracked)
        return recent

    def _other_row(self, tracked: _Tracked) -> dict[str, Any]:
        folder = tracked.folder
        row = folder.inbox_row(self._mtime_ns(tracked))
        row["title"] = row["title"] or folder._first_prompt()
        return _keyed(row, tracked.adapter, tracked.ref)

    def _inbox_row(self, catalog: CodexCatalog, path: Path, titles: dict[str, str], limit: int | None) -> dict[str, Any] | None:
        try:
            sig = signature(path)
        except OSError:
            return None
        cached = self._inbox.get(path)
        if cached is None or cached[0] != sig:
            # A changed file is re-read from its tail with a fresh folder, as the inbox always has.
            start = max(0, sig[0] - limit) if limit is not None else 0
            try:
                folder = RolloutTail(path, thread_id_of(path), start=start, adapter=self._codex()).read()
            except OSError:
                return None
            cached = self._inbox[path] = (sig, folder.inbox_fields(sig[1]))
        fields = cached[1]
        row = {
            **fields,
            "quiet": is_quiet(fields["status"], sig[1]),
            "project": catalog.project_name(fields["cwd"]),
            "title": titles.get(thread_id_of(path), ""),
        }
        ref = SessionRef(harness=Harness.CODEX.value, session_id=fields["id"], path=path, cwd=fields["cwd"] or None)
        return _keyed(row, self._codex(), ref)

    def inbox_fingerprint(self, history_days: int = DEFAULT_HISTORY_DAYS) -> str:
        """Changes when a chat file changes, and when a working chat turns quiet without any write."""
        catalog = self._require_catalog()
        parts = []
        with self._lock:
            for path in catalog.chats(history_days):
                try:
                    sig = signature(path)
                except OSError:
                    continue
                cached = self._inbox.get(path)
                quiet = bool(cached) and is_quiet(cached[1]["status"], sig[1])
                parts.append(f"{path.name}:{sig}:{quiet}")
            for tracked in self._others(history_days, pump=False):
                try:
                    sig = signature(tracked.ref.path) if tracked.ref.path else (0, 0)
                except OSError:
                    continue
                # Adapters whose state lives outside the session file (Cursor approvals) add a token for it.
                token_of = getattr(tracked.adapter, "state_token", None)
                token = token_of(tracked.ref) if callable(token_of) else ""
                parts.append(f"{tracked.ref.key}:{sig}:{token}:{is_quiet(tracked.folder._status(), sig[1])}")
        return "|".join(parts)

    def state(self, thread_id: str) -> TurnFolder | None:
        """Full-history state of one Codex thread (native id)."""
        with self._lock:
            return self._read_state(thread_id)

    def _read_state(self, thread_id: str) -> TurnFolder | None:
        catalog = self._require_catalog()
        path = catalog.find(thread_id)
        if path is None:
            return None
        tail = self._details.get(thread_id)
        if tail is None or tail.path != path:
            tail = self._details[thread_id] = RolloutTail(path, thread_id, adapter=self._codex())
        self._details.move_to_end(thread_id)
        while len(self._details) > self.max_details:
            self._details.popitem(last=False)
        try:
            state = tail.read()
        except OSError:
            # Archived or deleted since the last scan.
            del self._details[thread_id]
            return None
        state.title = catalog.titles().get(thread_id, state.title)
        state.project = catalog.project_name(state.cwd)
        return state

    def detail_dict(self, key: SessionKey | str) -> dict[str, Any] | None:
        """The `/api/threads/<key>` JSON; serialized under the lock before another reader feeds the source."""
        parsed = _parse_key(key)
        if parsed is None:
            return None
        native = parsed.native_id
        with self._lock:
            if parsed.harness is Harness.CODEX:
                state = self._read_state(native)
                if state is None:
                    return None
                path = self._details[native].path
                data = state.to_dict()
                try:
                    data["quiet"] = is_quiet(state.status, signature(path)[1])
                except OSError:
                    data["quiet"] = False
                ref = SessionRef(harness=Harness.CODEX.value, session_id=native, path=path, cwd=state.cwd or None)
                codex = self._codex()
                data["capabilities"] = asdict(codex.capabilities if codex else Capabilities())
                return _keyed(data, codex, ref)
            self._discover()
            tracked = self._tracked.get(parsed)
            if tracked is None:
                return None
            self._pump(tracked)
            data = tracked.folder.to_dict()
            data["title"] = data["title"] or tracked.folder._first_prompt()
            mtime = self._mtime_ns(tracked)
            data["quiet"] = is_quiet(data["status"], mtime) if mtime is not None else False
            # What the source can record, so the UI can say what is missing instead of guessing.
            data["capabilities"] = asdict(tracked.adapter.capabilities)
            return _keyed(data, tracked.adapter, tracked.ref)


def _parse_key(key: SessionKey | str) -> SessionKey | None:
    if isinstance(key, SessionKey):
        return key
    try:
        return SessionKey.parse(key)
    except ValueError:
        return None
