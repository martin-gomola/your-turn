"""Session engine: fold a session's history into one state, and serve it as API JSON.

`TurnFolder` is the single state machine (no I/O): every state change goes through
`fold(event)` on normalized harness `Event`s.

`SessionHub` owns every per-session state the app serves, reading every source the same way
through its adapter's cursor (`adapter.open(ref).read_new()` -> `fold`), and builds the inbox rows,
thread detail and stream fingerprint (`inbox_dicts`, `detail_dict`, `inbox_fingerprint`) from those
folders. No threads of its own: the caller drives reads, and one lock serializes request threads and
the event stream.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from yourturn.config import DEFAULT_HISTORY_DAYS
from yourturn.harness.base import (
    AgentMessage,
    ApprovalPending,
    ToolPending,
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
    SUBAGENT_TOOL,
    TURN_COMPLETED,
    CodexAdapter,
    format_ts,
    parse_ts,
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
    normalize_text,
    parse_answer,
    parse_decisions,
    parse_recap,
)
from yourturn.model import (
    Check,
    Decision,
    SessionKey,
    SessionRef,
    Step,
    Turn,
)

MAX_STEPS = 300
MAX_TURNS = 30
DEFAULT_TAIL_BYTES = 8 * 1024 * 1024
ASK_TOOLS = frozenset({ASK_USER_TOOL})


def iso(epoch: float) -> str:
    """Second-precision UTC timestamp, the inbox `updated_at` format."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def signature(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


class TurnFolder:
    """Folds one session's history (in order) into turns, checks, decisions, steps and usage.

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
        self._updated_ts: datetime | None = None
        self._last_message: tuple[int, str, str, Step] | None = None  # (turn, at, text, step)
        # A pending approval overlays the latest turn's state until the harness clears it.
        self.approval = ""
        self._attention_before = ""
        # The latest tool call still without a result (Claude Code), shown when the chat goes quiet.
        self.pending_tool = ""

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
        self.pending_tool = ""
        self._step(at, "turn", f"Turn {index} started")

    def _close_turn(self, at: str, stopped: str | None, duration: str) -> None:
        """End the current turn: `stopped` is the abort reason, or None for a completed turn."""
        turn = self._turn(at)
        turn.ended_at = at
        self.pending_tool = ""
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
        for decision in parse_decisions(text):
            self._decide(at, turn, decision)
        self.attention_key = ""
        if turn.next_kind not in {"unknown", "none"} and turn.next_text:
            self._attention(at, turn.next_kind, text)

    def _prompt(self, at: str, turn: Turn, text: str) -> None:
        for decision in self._pending():
            decision.chosen = normalize_text(text)
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
            normalize_text(str(args.get("chosen", ""))),
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
        elif isinstance(event, ToolPending):
            self.pending_tool = clip(event.text, 160)
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
            self.started_at = format_ts(event.ts)

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
            "pending_tool": self.pending_tool,
        }
        row["needs_you"] = needs_you(row)
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
            "pending_tool": self.pending_tool,
            "attention_key": self.attention_key,
            "version": self.version,
            "turns": turns,
            "steps": [asdict(step) for step in self.steps],
            "decisions": [asdict(decision) for decision in self.decisions],
            "needs_you": needs_you({**last, "status": self._status()}),
        }

    def _first_prompt(self) -> str:
        return next((clip(turn.prompt, 80) for turn in self.turns if turn.prompt), "")


def _json_object(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


# --- Hub -----------------------------------------------------------------------------------------


class _Tracked:
    """One discovered session; its cursor is opened on the first read."""

    __slots__ = ("adapter", "ref", "cursor", "folder", "truncations")

    def __init__(self, adapter: HarnessAdapter, ref: SessionRef) -> None:
        self.adapter = adapter
        self.ref = ref
        self.cursor: EventCursor | None = None
        self.folder = TurnFolder(ref)
        self.truncations = 0


class SessionHub:
    """Every chat the app serves, from every app, through one pipeline.

    Each discovered session gets one adapter cursor and one `TurnFolder` that folds only newly appended
    events. Inbox rows, thread detail and the stream fingerprint all read those same folders. A session is
    first read from its last `tail_bytes`, so a huge file stays cheap; its detail then says the history
    is partial.
    """

    def __init__(
        self,
        adapters: Sequence[HarnessAdapter],
        *,
        tail_bytes: int | None = DEFAULT_TAIL_BYTES,
        rescan_seconds: float = 3.0,
    ) -> None:
        self.adapters = list(adapters)
        self.tail_bytes = tail_bytes
        self.rescan_seconds = rescan_seconds
        self._tracked: dict[SessionKey, _Tracked] = {}
        self._scanned_at: float | None = None
        # Request threads and the event stream share the folders and cursors.
        self._lock = threading.RLock()

    @classmethod
    def for_codex_home(
        cls,
        codex_home: Path,
        *,
        scan_ttl: float = 3.0,
        tail_bytes: int | None = DEFAULT_TAIL_BYTES,
        claude_home: Path | None = None,
        cursor_home: Path | None = None,
        cursor_user_dir: Path | None = None,
    ) -> SessionHub:
        """Codex sessions under `codex_home`; `claude_home` / `cursor_home` also register those apps' sessions."""
        adapters: list[HarnessAdapter] = [CodexAdapter(home=codex_home)]
        if claude_home is not None:
            adapters.append(ClaudeAdapter(home=claude_home))
        if cursor_home is not None:
            adapters.append(CursorAdapter(home=cursor_home, user_dir=cursor_user_dir))
        return cls(adapters, tail_bytes=tail_bytes, rescan_seconds=scan_ttl)

    def _discover(self) -> None:
        now = time.monotonic()
        if self._scanned_at is not None and now - self._scanned_at < self.rescan_seconds:
            return
        seen: set[SessionKey] = set()
        for adapter in self.adapters:
            try:
                refs = list(adapter.discover())
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
                    self._tracked[key] = _Tracked(adapter, ref)
        for stale in set(self._tracked) - seen:
            del self._tracked[stale]
        self._scanned_at = now

    def _pump(self, tracked: _Tracked) -> None:
        if tracked.cursor is None:
            tracked.cursor = tracked.adapter.open(tracked.ref)
            if self.tail_bytes is not None:
                tracked.cursor.skip_to_tail(self.tail_bytes)
        events = tracked.cursor.read_new()
        if tracked.cursor.truncations != tracked.truncations:
            # The file shrank and the cursor replayed from the start: rebuild state.
            tracked.truncations = tracked.cursor.truncations
            tracked.folder = TurnFolder(tracked.ref)
        if events:
            tracked.folder.fold_many(events)
        if not tracked.folder.project:
            tracked.folder.project = tracked.adapter.project(tracked.ref)
        if title := tracked.adapter.title(tracked.ref):
            tracked.folder.title = title

    def _recent(self, history_days: int, *, pump: bool) -> list[_Tracked]:
        """Sessions written to within the history window, read up to date when `pump`."""
        self._discover()
        cutoff = (time.time() - history_days * 86400) * 1e9
        recent = [tracked for tracked in self._tracked.values() if (tracked.adapter.mtime_ns(tracked.ref) or 0) >= cutoff]
        if pump:
            for tracked in recent:
                self._pump(tracked)
        return recent

    def _get(self, key: SessionKey | str) -> _Tracked | None:
        """One session read up to date; a bare id means Codex."""
        parsed = _parse_key(key)
        if parsed is None:
            return None
        self._discover()
        tracked = self._tracked.get(parsed)
        if tracked is not None and tracked.ref.path is not None and not tracked.ref.path.exists():
            # Archived or deleted since the last scan.
            del self._tracked[parsed]
            return None
        if tracked is not None:
            self._pump(tracked)
        return tracked

    def _json(self, tracked: _Tracked, *, detail: bool) -> dict[str, Any]:
        """The one place a session becomes API JSON: an inbox row, or with `detail` the thread view."""
        folder, adapter, ref = tracked.folder, tracked.adapter, tracked.ref
        mtime = adapter.mtime_ns(ref)
        data = folder.to_dict() if detail else folder.inbox_fields(mtime)
        data["title"] = folder.title or folder._first_prompt()
        data["project"] = folder.project
        data["quiet"] = is_quiet(data["status"], mtime) if mtime is not None else False
        data["harness"] = ref.harness
        data["key"] = str(ref.key)
        data["handoff"] = asdict(adapter.handoff(ref, folder.cwd or None))
        if detail:
            # What the source can record, so the UI can say what is missing instead of guessing.
            data["capabilities"] = asdict(adapter.capabilities)
            data["history_truncated"] = bool(tracked.cursor and tracked.cursor.skipped_bytes)
        return data

    def inbox_dicts(self, history_days: int = DEFAULT_HISTORY_DAYS) -> list[dict[str, Any]]:
        """One row per user-facing chat written to in the window, newest first."""
        with self._lock:
            rows = [self._json(tracked, detail=False) for tracked in self._recent(history_days, pump=True)]
        rows.sort(key=lambda row: row["updated_at"], reverse=True)
        return rows

    def inbox_fingerprint(self, history_days: int = DEFAULT_HISTORY_DAYS) -> str:
        """Changes when a chat file changes, and when a working chat turns quiet without any write."""
        parts = []
        with self._lock:
            for tracked in self._recent(history_days, pump=False):
                try:
                    sig = signature(tracked.ref.path) if tracked.ref.path else (0, 0)
                except OSError:
                    continue
                # Adapters whose state lives outside the session file (Cursor approvals) add a token for it.
                token = tracked.adapter.state_token(tracked.ref)
                parts.append(f"{tracked.ref.key}:{sig}:{token}:{is_quiet(tracked.folder._status(), sig[1])}")
        return "|".join(parts)

    def folder(self, key: SessionKey | str) -> TurnFolder | None:
        """The folded state of one session, read up to date."""
        with self._lock:
            tracked = self._get(key)
            return tracked.folder if tracked else None

    def detail_dict(self, key: SessionKey | str) -> dict[str, Any] | None:
        """The `/api/threads/<key>` JSON; serialized under the lock before another reader feeds the source."""
        with self._lock:
            tracked = self._get(key)
            return self._json(tracked, detail=True) if tracked else None


def _parse_key(key: SessionKey | str) -> SessionKey | None:
    if isinstance(key, SessionKey):
        return key
    try:
        return SessionKey.parse(key)
    except ValueError:
        return None
