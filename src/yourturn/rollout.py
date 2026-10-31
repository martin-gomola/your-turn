"""Compatibility facade: the old Codex `Sessions` API, delegating to `yourturn.engine.SessionHub`.

All folding, discovery and serialization now live in `yourturn.engine` (`TurnFolder`,
`RolloutParser`, `RolloutTail`, `CodexCatalog`, `SessionHub`). Harness-neutral types live in
`yourturn.model`, judgements in `yourturn.heuristics`, Codex record knowledge in
`yourturn.harness.codex`; they are re-exported here so existing imports keep working.
"""

from __future__ import annotations

import time  # noqa: F401  (tests patch `yourturn.rollout.time.time`, i.e. the shared `time` module)
from pathlib import Path
from typing import Any

from yourturn.config import DEFAULT_HISTORY_DAYS
from yourturn.engine import (  # noqa: F401  (re-exported)
    INBOX_TAIL_BYTES,
    MAX_DETAILS as MAX_TAILS,
    MAX_STEPS,
    MAX_TURNS,
    CodexCatalog,
    RolloutParser,
    RolloutTail,
    SessionHub,
    TurnFolder,
    iso as _iso,
    signature as _signature,
)
from yourturn.heuristics import (  # noqa: F401  (re-exported)
    ACTION_KINDS,
    DOC_SUFFIXES,
    MAX_TEXT,
    QUIET_SECONDS,
    check_key as _check_key,
    check_state,
    check_status,
    clip as _clip,
    code_paths,
    is_check_command,
    is_quiet,
    needs_you,
    parse_answer,
    parse_recap,
)
from yourturn.model import UUID as THREAD_ID, Check, Decision, Step, Turn  # noqa: F401  (re-exported)
from yourturn.harness.codex import (  # noqa: F401  (re-exported)
    DECISION_TOOL,
    INJECTED_CONTEXT,
    QUESTION_REPLY,
    ROLLOUT_GLOB,
    SHELL_WRAPPERS,
    TOKEN_FIELDS,
    WANTED,
    CodexAdapter,
    CodexCursor,
    _command,
    _texts,
    _token_counts,
    thread_id_of,
    user_text,
)

# The per-thread state type is now the engine's folder (same attribute names as before).
ThreadState = TurnFolder


class Sessions:
    """Codex home view kept for existing callers; every method delegates to one `SessionHub`."""

    def __init__(self, codex_home: Path, scan_ttl: float = 3.0) -> None:
        self.hub = SessionHub.for_codex_home(codex_home, scan_ttl=scan_ttl)
        self.catalog: CodexCatalog = self.hub.catalog  # type: ignore[assignment]
        self.root = self.catalog.root
        self.index = self.catalog.index
        self.scan_ttl = scan_ttl

    def project_name(self, cwd: str) -> str:
        return self.catalog.project_name(cwd)

    def rollouts(self) -> list[Path]:
        return self.catalog.rollouts()

    def is_subagent(self, path: Path) -> bool:
        return self.catalog.is_subagent(path)

    def chats(self, history_days: int = DEFAULT_HISTORY_DAYS) -> list[Path]:
        return self.catalog.chats(history_days)

    def find(self, thread_id: str) -> Path | None:
        return self.hub.find(thread_id)

    def titles(self) -> dict[str, str]:
        return self.catalog.titles()

    def inbox(self, history_days: int = DEFAULT_HISTORY_DAYS) -> list[dict[str, Any]]:
        """Status and latest-turn summary per chat, parsed from each file's tail only."""
        # Read the module global at call time so `INBOX_TAIL_BYTES` stays patchable.
        return self.hub.inbox_dicts(history_days, tail_bytes=INBOX_TAIL_BYTES)

    def inbox_fingerprint(self, history_days: int = DEFAULT_HISTORY_DAYS) -> str:
        return self.hub.inbox_fingerprint(history_days)

    def state(self, thread_id: str) -> TurnFolder | None:
        return self.hub.state(thread_id)

    def snapshot(self, thread_id: str) -> dict[str, Any] | None:
        """JSON-ready state (`SessionHub.detail_dict`)."""
        return self.hub.detail_dict(thread_id)
