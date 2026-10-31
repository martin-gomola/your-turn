"""Harness-neutral judgements: what a final answer asks of the user, what counts as a check, and
whether a turn's edits are covered. Adapters feed these plain text, commands, and paths."""

from __future__ import annotations

import re
import time
from typing import Any

from yourturn.model import CheckState, Turn

MAX_TEXT = 280
# A working chat whose source stops changing for this long is waiting on an approval, a long command, or stalled.
QUIET_SECONDS = 120
# Edits to these alone have nothing for tests or linters to check.
DOC_SUFFIXES = (".md", ".mdx", ".rst", ".txt")
ACTION_KINDS = {"answer", "review", "approve", "run", "decide", "do"}
MARKDOWN_EMPHASIS = re.compile(r"\*\*|__|`")
ANSWER_LABEL = re.compile(
    # The leading class must not match newlines: with MULTILINE, `\s` there is quadratic on blank lines.
    r"^[ \t#>*_-]*(outcome|result|next step|your next step|next|recap)[*_\s]*:[*_\s]*(.*)$", re.IGNORECASE | re.MULTILINE
)
NEXT_KIND = re.compile(r"^(answer|review|approve|run|decide)\b\s*[:\-–]?\s*", re.IGNORECASE)
NOTHING_NEEDED = re.compile(r"^(none|nothing|no action|n/a|—|-)\b", re.IGNORECASE)
# A check is a command that runs the tool itself, so `rg pytest` (exit 1 when nothing matches) is not one.
CHECK_COMMAND = re.compile(
    r"(pytest|vitest|jest|mypy|ruff|eslint|tsc|pyright|go test|cargo (test|clippy)|"
    r"(npm|pnpm|yarn|bun) (run )?(test|lint|check|typecheck|build)|make (check|test|lint|ci|build))\b"
)
CHECK_PREFIX = re.compile(r"((cd|source) \S+ *&& *|[A-Z_][A-Z0-9_]*=\S* +|(uv run|uvx|npx|bunx|pnpm exec|poetry run|python3? -m) +)*")
HEADING = re.compile(r"#{1,6}\s+.*|(\*\*|__)[^*_\n]+\1:?")
REQUEST = re.compile(r"^(please (provide|share|confirm|send|tell)|can you|could you)\b", re.IGNORECASE)
# An imperative at a sentence start, or after "please" / "you can" and similar; "I ran pytest" never matches.
ASK_LEAD = r"(?:^|[.!?:;]\s+|\bplease\s+|\byou (?:can|could|should|need to|may want to|might want to)\s+)"
# "run into", "run out", "run 2 took 5s", "run nightly" are prose, not asks.
RUN_NOUN = r"(?!(?:time|into|out|across|over|away|one|two|three|nightly|daily|weekly|\d)\b)"
FINAL_ASKS = (
    ("run", re.compile(ASK_LEAD + r"run:?\s+" + RUN_NOUN + r"\S", re.IGNORECASE)),
    ("review", re.compile(ASK_LEAD + r"(?:review|take a look at|have a look at):?\s+(?!apps?\b)\S", re.IGNORECASE)),
    # Not "let me know if…": it is the most common sign-off and rarely a real request.
    ("answer", re.compile(r"\b(?:let me know (?:whether|which)|would you like|do you want|should i|shall i)\b", re.IGNORECASE)),
)
FENCE = re.compile(r"```.*?(?:```|\Z)", re.DOTALL)


def clip(text: str, limit: int = MAX_TEXT) -> str:
    text = " ".join(MARKDOWN_EMPHASIS.sub("", text).split())
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def parse_answer(text: str) -> tuple[str, str, str, bool]:
    """Return (outcome, next_kind, next_text, formatted) from a final answer.

    Answers following the Your Turn handoff format carry `Outcome:` and `Next step:` lines; anything else
    falls back to the first prose paragraph. The next step is then inferred from the final paragraph (a
    `run`, `review`, or `answer` ask, or a closing question), or an `answer` when the reply opens with a request.
    """
    labels = {match.group(1).lower(): match.group(2) for match in ANSWER_LABEL.finditer(text)}
    outcome = labels.get("outcome") or labels.get("result")
    step = labels.get("your next step") or labels.get("next step") or labels.get("next")
    if outcome is None:
        # Code blocks are not prose: `then run ./deploy` in a script is not an ask.
        parts = [part.strip() for part in re.split(r"\n\s*\n", FENCE.sub("", text)) if part.strip()]
        flat = [" ".join(line.strip(" -*#>") for line in part.splitlines()).strip() for part in parts]
        body = [line for part, line in zip(parts, flat) if not HEADING.fullmatch(part) and not line.endswith(":")]
        last = " ".join(flat[-2:]) if len(flat) > 1 and flat[-2].endswith(":") else flat[-1] if flat else ""
        kind = next((name for name, ask in FINAL_ASKS if ask.search(last)), "answer" if last.endswith("?") else "")
        request = last if kind else ""
        if not kind and flat and REQUEST.match(flat[0]):
            kind, request = "answer", " ".join(flat[:2]) if flat[0].endswith(":") else flat[0]
        summary = body[0] if body else flat[0] if flat else ""
        return clip(summary, 200), kind or "unknown", clip(request, 200), False
    kind, step_text = "unknown", clip(step or "", 200)
    if step is not None:
        if NOTHING_NEEDED.match(step_text):
            kind, step_text = "none", ""
        elif match := NEXT_KIND.match(step_text):
            kind, step_text = match.group(1).lower(), step_text[match.end():]
        else:
            kind = "do"
    return clip(outcome, 200), kind, step_text, True


def parse_recap(text: str) -> str:
    """The whole-chat summary from a `Recap:` line, which the handoff asks for after the first turn."""
    recap = next((m.group(2) for m in ANSWER_LABEL.finditer(text) if m.group(1).lower() == "recap"), "")
    return clip(recap, 400)


def needs_you(entry: dict[str, Any]) -> bool:
    """A pending question, or a finished turn that recorded an action for the user."""
    if entry["status"] == "waiting":
        return True
    return entry["status"] == "done" and entry["next_kind"] in ACTION_KINDS and bool(entry["next_text"])


def is_check_command(command: str) -> bool:
    """`uv run pytest -q` and `cd web && npm test` are checks; `rg pytest` is not."""
    return CHECK_COMMAND.match(command, CHECK_PREFIX.match(command).end()) is not None


def check_key(command: str) -> str:
    """`cd repo && pytest` and `pytest` are the same check."""
    return re.sub(r"^cd \S+ *&& *", "", command)


def is_doc_path(path: str) -> bool:
    lowered = path.lower()
    return lowered.endswith(DOC_SUFFIXES) or "/docs/" in lowered or lowered.startswith("docs/")


def code_paths(paths: list[str]) -> list[str]:
    return [path for path in paths if not is_doc_path(path)]


def check_status(turn: Turn | None) -> CheckState:
    """A failed latest run wins; code edits without a later check are unchecked; documentation-only edits
    are not applicable rather than unchecked, so a README fix raises no alarm."""
    if turn is None:
        return CheckState.NOT_APPLICABLE
    if any(check.exit_code not in (0, None) for check in turn.checks):
        return CheckState.FAILED
    if code_paths(turn.files) and (not turn.checks or turn.edited_after_check):
        return CheckState.UNCHECKED
    if not turn.checks:
        return CheckState.NOT_APPLICABLE
    # A check without an exit code has not reported back yet.
    return CheckState.PASSED if all(check.exit_code == 0 for check in turn.checks) else CheckState.UNKNOWN


def check_state(turn: Turn | None) -> str:
    """Legacy inbox value read by app.js: `failed`, `unchecked`, or empty."""
    state = check_status(turn)
    return state.value if state in (CheckState.FAILED, CheckState.UNCHECKED) else ""


def is_quiet(status: str, modified_ns: int, now: float | None = None) -> bool:
    """A working chat whose source has not changed for a while."""
    return status == "working" and (now or time.time()) - modified_ns / 1e9 > QUIET_SECONDS
