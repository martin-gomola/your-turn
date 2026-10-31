"""Claude Code harness adapter: tails `~/.claude/projects/<slug>/<session>.jsonl` transcripts.

Read-only, no subprocesses, no network. Claude Code writes one record per content block (a
thinking block, a text block and each `tool_use` are separate `assistant` records sharing one
`message.id`), and a tool's outcome arrives later as a `tool_result` block in a `user` record.
Turn boundaries are inferred: a real user prompt starts a turn, a text block whose stop reason is
not `tool_use` ends it.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from yourturn.harness.base import (
    AgentMessage,
    CommandRun,
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
from yourturn.harness.codex import (
    ASK_USER_TOOL,
    DECISION_TOOL,
    OUTPUT_TAIL,
    SUBAGENT_TOOL,
    TURN_COMPLETED,
    CodexCursor,
    _command,
    parse_ts,
)
from yourturn.heuristics import clip
from yourturn.model import Capabilities, Handoff, Harness, SessionRef

SESSION_GLOB = "*/*.jsonl"  # Sub-agent transcripts live deeper, in <slug>/<session>/subagents/.
EDIT_TOOLS = frozenset({"Edit", "Write", "MultiEdit", "NotebookEdit"})
SUBAGENT_TOOLS = frozenset({"Task", "Agent"})
ASK_TOOL = "AskUserQuestion"
# Substring prefilter: attachments, file-history snapshots and queue records are never parsed.
WANTED = (b'"user"', b'"assistant"', b'"summary"', b'"custom-title"')
HEAD_LINES = 50
INTERRUPTED = "[Request interrupted by user"
LOCAL_OUTPUT = "<local-command-std"
# Claude Code wraps slash commands, hook output and reminders in tags; none of it is what the user typed.
INJECTED = re.compile(
    r"<(system-reminder|task-notification|command-message|local-command-[\w-]+|user-prompt-submit-hook)\b[^>]*>.*?</\1>",
    re.DOTALL,
)
COMMAND_PARTS = re.compile(r"</?command-(?:name|args)>")
ANSWER = re.compile(r'"([^"]*)"="([^"]*)"')


def claude_home() -> Path:
    """`$CLAUDE_CONFIG_DIR`, else `~/.claude` (Claude Code's own default)."""
    raw = os.environ.get("CLAUDE_CONFIG_DIR")
    return Path(raw).expanduser() if raw else Path.home() / ".claude"


def prompt_text(content: object) -> str:
    """What the user typed in a `user` record's content ("" for tool results and injected context)."""
    if isinstance(content, list):
        content = "\n".join(
            block["text"] for block in content if isinstance(block, dict) and block.get("type") == "text" and isinstance(block.get("text"), str)
        )
    if not isinstance(content, str):
        return ""
    return COMMAND_PARTS.sub(" ", INJECTED.sub("", content)).strip()


def _result_text(content: object) -> str:
    if isinstance(content, list):
        content = "\n".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return content if isinstance(content, str) else ""


def _tool_name(name: str) -> str:
    """`mcp__server__tool` -> `server · tool`, as Codex MCP calls are named."""
    if name.startswith("mcp__"):
        server, _, tool = name[5:].partition("__")
        return DECISION_TOOL if tool == DECISION_TOOL else f"{server} · {tool}"
    return name


def _first_line(command: object) -> str:
    return _command({"command": command if isinstance(command, str) else ""})


class ClaudeCursor(CodexCursor):
    """Incremental reader over one Claude Code transcript (implements `EventCursor`)."""

    def __init__(self, ref: SessionRef) -> None:
        super().__init__(ref)
        self._clear()

    def _clear(self) -> None:
        self._meta_sent = False
        self._title = ""
        self._settings: tuple[str, str] | None = None  # (model, effort) last announced
        self._tools: dict[str, tuple[str, dict[str, Any]]] = {}  # tool_use id -> (name, input)
        self._messages: set[str] = set()
        # ponytail: totals restart at the read start, so a tail read under-counts; a full read is exact.
        self._totals = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    def reset(self) -> None:
        super().reset()
        self._clear()

    def _head_events(self) -> list[Event]:
        """The session header comes from the first record that carries a `cwd`."""
        with self._path.open("rb") as handle:
            for _ in range(HEAD_LINES):
                raw = handle.readline()
                if not raw:
                    break
                record = self._parse(raw)
                if record is not None and record.get("cwd"):
                    return self._meta(record)
        return []

    def _parse(self, raw: bytes) -> dict[str, Any] | None:
        if not any(marker in raw for marker in WANTED):
            return None
        try:
            record = json.loads(raw.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            return None
        return record if isinstance(record, dict) else None

    def _meta(self, record: dict[str, Any]) -> list[Event]:
        if self._meta_sent or not record.get("cwd"):
            return []
        self._meta_sent = True
        version, branch = record.get("version"), record.get("gitBranch")
        return [
            Meta(
                ts=parse_ts(record.get("timestamp")),
                session_id=str(record.get("sessionId") or self._ref.session_id),
                cwd=str(record["cwd"]),
                harness=Harness.CLAUDE.value,
                model_provider="anthropic",
                cli_version=clip(version, 120) if isinstance(version, str) else None,
                git_branch=clip(branch, 160) if isinstance(branch, str) and branch else None,
                subagent=bool(record.get("isSidechain")),
                parent_id="",
            )
        ]

    def _events(self, record: dict[str, Any]) -> list[Event]:
        kind = record.get("type")
        if kind in ("summary", "custom-title"):
            title = record.get("summary") if kind == "summary" else record.get("customTitle")
            if not isinstance(title, str) or not title or title == self._title:
                return []
            self._title = title
            return [Meta(title=clip(title, 160))]
        if kind not in ("user", "assistant"):
            return []
        ts = parse_ts(record.get("timestamp"))
        message = record.get("message") if isinstance(record.get("message"), dict) else {}
        events = self._meta(record)
        if kind == "user":
            if not record.get("isMeta"):
                events.extend(self._user(ts, message.get("content")))
        else:
            events.extend(self._assistant(ts, record, message))
        return events

    # -- user records: prompts and tool results ----------------------------------------------------

    def _user(self, ts: datetime | None, content: object) -> list[Event]:
        events: list[Event] = []
        for block in content if isinstance(content, list) else []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                events.extend(self._result(ts, block))
        text = prompt_text(content)
        if LOCAL_OUTPUT in str(content):
            # A built-in slash command (/model, /clear) answered locally: its turn is over, no agent reply follows.
            events.append(TurnEnded(ts=ts, reason=TURN_COMPLETED))
        elif text.startswith(INTERRUPTED):
            events.append(TurnEnded(ts=ts, reason="interrupted"))
        elif text:
            events += [TurnStarted(ts=ts), UserMessage(ts=ts, text=text)]
        return events

    def _result(self, ts: datetime | None, block: dict[str, Any]) -> list[Event]:
        pending = self._tools.pop(str(block.get("tool_use_id")), None)
        if pending is None:
            return []  # Its tool_use came before the read start.
        name, arguments = pending
        failed = bool(block.get("is_error"))
        output = _result_text(block.get("content"))
        if name == "Bash":
            return [
                CommandRun(
                    ts=ts,
                    command=_first_line(arguments.get("command")),
                    exit_code=1 if failed else 0,
                    output_tail=output[-OUTPUT_TAIL:] or None,
                )
            ]
        if name in EDIT_TOOLS:
            path = arguments.get("file_path") or arguments.get("notebook_path")
            return [FilesEdited(ts=ts, paths=(str(path),) if path else (), ok=not failed)]
        if name == ASK_TOOL:
            questions = [clip(str(q.get("question", ""))) for q in arguments.get("questions") or [] if isinstance(q, dict)]
            answers = {clip(q): clip(a, 120) for q, a in ANSWER.findall(output)}
            # A dismissed question still stops waiting; it was not answered.
            return [UserMessage(ts=ts, answers=tuple((q, answers.get(q, "dismissed")) for q in questions))]
        return [ToolCall(ts=ts, name=_tool_name(name), arguments=json.dumps(arguments, ensure_ascii=False), ok=not failed)]

    # -- assistant records: one content block each -------------------------------------------------

    def _assistant(self, ts: datetime | None, record: dict[str, Any], message: dict[str, Any]) -> list[Event]:
        events: list[Event] = []
        model, effort = message.get("model"), record.get("effort")
        if isinstance(model, str) and model and not model.startswith("<"):  # "<synthetic>" is not a model.
            settings = (clip(model, 120), clip(effort, 80) if isinstance(effort, str) else "")
            if settings != self._settings:
                self._settings = settings
                events.append(Meta(ts=ts, model=settings[0], reasoning_effort=settings[1]))
        events.extend(self._usage(ts, message))
        content = message.get("content")
        texts: list[str] = []
        for block in content if isinstance(content, list) else []:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "thinking":
                events.append(Reasoning(ts=ts, text=str(block.get("thinking") or "")))
            elif kind == "text" and isinstance(block.get("text"), str):
                texts.append(block["text"])
            elif kind == "tool_use":
                events.extend(self._tool_use(ts, block))
        if texts:
            events.append(AgentMessage(ts=ts, text="\n".join(texts)))
            if message.get("stop_reason") != "tool_use":
                events.append(TurnEnded(ts=ts, reason=TURN_COMPLETED))
        return events

    def _tool_use(self, ts: datetime | None, block: dict[str, Any]) -> list[Event]:
        name = str(block.get("name") or "")
        arguments = block.get("input") if isinstance(block.get("input"), dict) else {}
        if name in SUBAGENT_TOOLS:
            label = arguments.get("description") or arguments.get("subagent_type") or name
            return [ToolCall(ts=ts, name=SUBAGENT_TOOL, arguments=str(label), ok=True)]
        # Everything else is reported once its result arrives, with the outcome.
        self._tools[str(block.get("id"))] = (name, arguments)
        if name != ASK_TOOL:
            return []
        # Questions are shown as soon as they are asked: the agent is now waiting for the user.
        return [
            ToolCall(
                ts=ts,
                name=ASK_USER_TOOL,
                arguments=json.dumps(
                    {
                        "title": question.get("question", ""),
                        "options": [o.get("label", "") if isinstance(o, dict) else str(o) for o in question.get("options") or []],
                    },
                    ensure_ascii=False,
                ),
            )
            for question in arguments.get("questions") or []
            if isinstance(question, dict)
        ]

    def _usage(self, ts: datetime | None, message: dict[str, Any]) -> list[Event]:
        """Per-request usage, counted once per API message (its blocks repeat the same numbers)."""
        usage, message_id = message.get("usage"), message.get("id")
        if not isinstance(usage, dict) or not message_id or message_id in self._messages:
            return []
        self._messages.add(message_id)
        counts = {key: value if type(value) is int and value >= 0 else 0 for key, value in usage.items()}
        cached = counts.get("cache_read_input_tokens", 0)
        prompt = counts.get("input_tokens", 0) + counts.get("cache_creation_input_tokens", 0) + cached
        output = counts.get("output_tokens", 0)
        last = {"input_tokens": prompt, "cached_input_tokens": cached, "output_tokens": output, "total_tokens": prompt + output}
        for key, value in last.items():
            self._totals[key] += value
        totals = dict(self._totals)
        return [
            Usage(
                ts=ts,
                input_tokens=totals["input_tokens"],
                output_tokens=totals["output_tokens"],
                cached_input_tokens=totals["cached_input_tokens"],
                total_tokens=totals["total_tokens"],
                total=totals,
                last=last,
            )
        ]


class ClaudeAdapter:
    """Finds Claude Code transcripts and opens cursors on them (implements `HarnessAdapter`)."""

    name: str = Harness.CLAUDE.value
    capabilities: Capabilities = Capabilities(
        can_resume=True,
        has_usage=True,
        has_tool_calls=True,
        has_checks=True,
        live_tail=True,
    )

    def __init__(self, home: Path | None = None, *, include_subagents: bool = False, max_age_days: float | None = None) -> None:
        self.home = home or claude_home()
        self.include_subagents = include_subagents
        self.max_age_days = max_age_days
        self._heads: dict[Path, tuple[bool, str | None]] = {}

    def _projects(self, root: Path | None) -> Path:
        # The hub passes one root to every adapter; only a Claude home (with projects/) applies here.
        if root is not None and (root / "projects").is_dir():
            return root / "projects"
        return self.home / "projects"

    def available(self, root: Path | None = None) -> bool:
        return self._projects(root).is_dir()

    def _head(self, path: Path) -> tuple[bool, str | None]:
        """(is_sidechain, cwd) from the first record carrying a cwd; cached since it never changes."""
        cached = self._heads.get(path)
        if cached is None:
            sidechain, cwd = False, None
            try:
                with path.open("rb") as handle:
                    for _ in range(HEAD_LINES):
                        record = json.loads(handle.readline() or b"null")
                        if not isinstance(record, dict):
                            break
                        if record.get("cwd"):
                            sidechain, cwd = bool(record.get("isSidechain")), str(record["cwd"])
                            break
            except (OSError, ValueError):
                pass
            cached = self._heads[path] = (sidechain, cwd)
        return cached

    def discover(self, root: Path | None = None) -> Iterator[SessionRef]:
        projects = self._projects(root)
        if not projects.is_dir():
            return
        found: list[tuple[float, Path]] = []
        for path in projects.glob(SESSION_GLOB):
            try:
                found.append((path.stat().st_mtime, path))
            except OSError:
                continue
        found.sort(reverse=True)
        cutoff = time.time() - self.max_age_days * 86400 if self.max_age_days is not None else None
        for mtime, path in found:
            if cutoff is not None and mtime < cutoff:
                break
            sidechain, cwd = self._head(path)
            if sidechain and not self.include_subagents:
                continue
            yield SessionRef(harness=self.name, session_id=path.stem, path=path, cwd=cwd)

    def open(self, ref: SessionRef) -> ClaudeCursor:
        return ClaudeCursor(ref)

    def handoff(self, ref: SessionRef, cwd: str | None) -> Handoff:
        where = cwd or ref.cwd
        return Handoff(resume_command=f"claude --resume {ref.session_id}", open_path=where, terminal_cwd=where)

    @staticmethod
    def project(ref: SessionRef) -> str:
        """Project name: the cwd's last folder, else decoded from the `-Users-me-repo` folder slug."""
        if ref.cwd:
            return Path(ref.cwd).name
        # ponytail: the slug maps both "/" and "-" to "-", so "my-repo" decodes as "repo"; cwd is preferred.
        return ref.path.parent.name.rsplit("-", 1)[-1] if ref.path else ""
