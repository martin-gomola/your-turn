"""Harness-neutral judgements: what a final answer asks of the user, what counts as a check, and
whether a turn's edits are covered. Adapters feed these plain text, commands, and paths."""

from __future__ import annotations

import posixpath
import re
import time
from typing import Any

from yourturn.model import Turn

MAX_TEXT = 280
# A working chat whose source stops changing for this long is waiting on an approval, a long command, or stalled.
QUIET_SECONDS = 120
# Edits to these alone have nothing for tests or linters to check.
DOC_SUFFIXES = (".md", ".mdx", ".rst", ".txt")
SCRATCH_ROOTS = ("/tmp/", "/var/folders/")
PATH_ALIASES = (("/private/tmp", "/tmp"), ("/private/var", "/var"))
ACTION_KINDS = {"answer", "review", "approve", "run", "decide", "do"}
MARKDOWN_EMPHASIS = re.compile(r"\*\*|__|`")
MARKDOWN_LINK = re.compile(r"!?\[([^\]]*)\]\([^)\s]*\)")
ANSWER_LABEL = re.compile(
    # The leading class must not match newlines: with MULTILINE, `\s` there is quadratic on blank lines.
    r"^[ \t#>*_`-]*(outcome|result|next step|your next step|next|ďalší krok|recap)[*_\s]*:[*_\s]*(.*)$",
    re.IGNORECASE | re.MULTILINE,
)
NEXT_KIND = re.compile(r"^(answer|review|approve|run|decide)\b\s*[:\-–]?\s*", re.IGNORECASE)
NOTHING_NEEDED = re.compile(r"^(none|nothing|no action|no further action|n/a|—|-)\b", re.IGNORECASE)
# Slovak "none" only as the whole step: "Nič, len obnov stránku" is still an instruction.
NOTHING_NEEDED_SK = re.compile(r"^(žiadny|žiadne|nič)[.!…]?$", re.IGNORECASE)
# A check is a command that runs the tool itself, so `rg pytest` (exit 1 when nothing matches) is not one.
CHECK_COMMAND = re.compile(
    r"(pytest|unittest|vitest|jest|mypy|ruff|eslint|tsc|pyright|node --test|swift test|go test|cargo (test|clippy)|"
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
# `Decision: <question> -> <chosen> (over <alternatives>). <reason>`, bold or plain, `->` or `→`.
DECISION = re.compile(r"^[ \t#>*_`-]*decision[*_ \t]*:[*_ \t]*(.+?)\s*(?:->|→)\s*(.+?)\s*$", re.IGNORECASE | re.MULTILINE)
OVER = re.compile(r"^(.*?)\s*\(over ([^)]*)\)\.?\s*(.*)$", re.IGNORECASE)
ALTERNATIVES = re.compile(r"\s*(?:,|\bor\b)\s*")


def normalize_text(text: str) -> str:
    return " ".join(MARKDOWN_EMPHASIS.sub("", MARKDOWN_LINK.sub(r"\1", text)).split())


def clip(text: str, limit: int = MAX_TEXT) -> str:
    text = normalize_text(text)
    return text if len(text) <= limit else f"{text[: limit - 1]}…"


def parse_answer(text: str) -> tuple[str, str, str, bool]:
    """Return (outcome, next_kind, next_text, formatted) from a final answer.

    Answers following the Your Turn handoff format carry `Outcome:` and `Next step:` lines; anything else
    falls back to the first prose paragraph. The next step is then inferred from the final paragraph (a
    `run`, `review`, or `answer` ask, or a closing question), or an `answer` when the reply opens with a request.
    """
    # A `Next step:` inside a code example must not override the real handoff.
    labels = {match.group(1).lower(): match.group(2) for match in ANSWER_LABEL.finditer(FENCE.sub("", text))}
    outcome = labels.get("outcome") or labels.get("result")
    step = labels.get("your next step") or labels.get("next step") or labels.get("next") or labels.get("ďalší krok")
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
        if NOTHING_NEEDED.match(step_text) or NOTHING_NEEDED_SK.match(step_text):
            kind, step_text = "none", ""
        elif match := NEXT_KIND.match(step_text):
            kind, step_text = match.group(1).lower(), step_text[match.end():]
        else:
            kind = "do"
    return clip(outcome, 200), kind, step_text, True


def parse_decisions(text: str) -> list[dict[str, Any]]:
    """Every `Decision:` line of an answer as `{question, options, chosen, reason}` (chosen first in options)."""
    decisions = []
    for match in DECISION.finditer(FENCE.sub("", text)):
        question, rest = match.group(1), match.group(2)
        if over := OVER.match(rest):
            chosen, others, reason = over.group(1), [o for o in ALTERNATIVES.split(over.group(2)) if o.strip()], over.group(3)
        else:
            chosen, _, reason = rest.partition(". ")
            others = []
        chosen = clip(chosen.rstrip(" ."), 120)
        if not chosen:
            continue
        options = [chosen, *(clip(option, 120) for option in others)]
        decisions.append({"question": clip(question.rstrip(" ?") + "?"), "options": options, "chosen": chosen, "reason": clip(reason)})
    return decisions


def parse_recap(text: str) -> str:
    """The whole-chat summary from a `Recap:` line, which the handoff asks for after the first turn."""
    recap = next((m.group(2) for m in ANSWER_LABEL.finditer(FENCE.sub("", text)) if m.group(1).lower() == "recap"), "")
    return clip(recap, 400)


def needs_you(entry: dict[str, Any]) -> bool:
    """A pending question, or a finished turn that recorded an action for the user."""
    if entry["status"] == "waiting":
        return True
    return entry["status"] == "done" and entry["next_kind"] in ACTION_KINDS and bool(entry["next_text"])


def is_check_command(command: str) -> bool:
    """`uv run pytest -q` and `cd web && npm test` are checks; `rg pytest` is not."""
    return CHECK_COMMAND.match(command, CHECK_PREFIX.match(command).end()) is not None


# Constructs that change which commands run, or hide text that is not run: reading stops at them.
UNMODELED = ("$(", "`", "<<", "<(", ">(", "(", ")", "{", "}")
SHELL_KEYWORDS = {"if", "then", "else", "elif", "fi", "for", "while", "until", "do", "done", "case", "esac", "function", "select", "!"}
# Builtins that end, replace or reroute the shell's run, change how it runs (`set -n`, `set -e`), or run
# shell code this does not read (`source`, `.`): a later command may never run, or its exit not be the shell's.
CONTROL_FLOW = {"exit", "exec", "return", "eval", "trap", "break", "continue", "logout", "set", "source", "."}
ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")


def _command_lists(command: str) -> tuple[list[list[tuple[str, str]]], bool]:
    """A shell command as its `;`/newline-separated lists of (joining operator, simple command).

    Not a shell parser: it honors quotes, backslashes, `#` comments and line continuations, and stops at
    anything it does not model (heredocs, substitutions, groups, background jobs, compound keywords).
    The flag is False when it stopped there; what came before is still returned, the rest is dropped.
    """
    lists: list[list[tuple[str, str]]] = [[]]
    current, joined, quote, i, complete = "", "", "", 0, True

    def end(operator: str) -> bool:
        """Close the simple command read so far; False when there is none or it opens a compound."""
        nonlocal current, joined
        text = current.strip()
        if not text or text.split()[0] in SHELL_KEYWORDS:
            return False
        lists[-1].append((joined, text))
        current, joined = "", operator
        return True

    while complete and i < len(command):
        char, pair = command[i], command[i : i + 2]
        redirect = char == "&" and (current.endswith((">", "<")) or command[i + 1 : i + 2] == ">")  # 2>&1, &>
        if quote:
            step = 2 if char == "\\" and quote == '"' else 1
            quote = "" if char == quote else quote
            current, i = current + command[i : i + step], i + step
        elif char == "\\":
            current, i = current + ("" if pair == "\\\n" else pair), i + 2
        elif char in "'\"":
            quote, current, i = char, current + char, i + 1
        elif char == "#" and (not current or current[-1] in " \t"):
            i = command.find("\n", i) if "\n" in command[i:] else len(command)
        elif pair == "${" and (close := command.find("}", i)) > 0:
            current, i = current + command[i : close + 1], close + 1
        elif command.startswith(UNMODELED, i) or (char == "&" and pair != "&&" and not redirect):
            complete = False
        elif pair in ("&&", "||") or (char == "|" and pair != "||"):
            operator = pair if pair in ("&&", "||") else "|"
            complete, i = end(operator), i + len(operator)
        elif char in ";\n":
            if current.strip():
                complete = end("")
                lists.append([])
            else:
                # A newline right after `&&`, `||` or `|` continues the list; an empty `;` is malformed.
                complete = char == "\n"
            i += 1
        else:
            current, i = current + char, i + 1
    if complete and (quote or (current.strip() and not end("")) or (not current.strip() and joined)):
        complete = False
    return [commands for commands in lists if commands], complete


def _program(command: str) -> str:
    """The program a simple command runs, after any `NAME=value` assignments."""
    return next((word for word in command.split() if not ASSIGNMENT.match(word)), "")


def check_result(command: str, exit_code: int | None) -> tuple[bool, int | None]:
    """Whether `command` runs a check, and the exit code that check is proven to have had (None: unproven).

    Only the whole command's exit code is known. It proves a check passed when the check is in the last
    list and that list is joined by `&&` alone, so exit 0 means every part of it ran and passed. It proves a
    failure only when the check runs alone as the last list, since a failed `cd` before `&& pytest` skips
    the test. `pytest || true`, `pytest; echo done`, `false && pytest`, anything piped, and any command
    with `exit`, `exec`, `set`, `source` or `.` prove nothing.
    """
    lists, complete = _command_lists(command)
    segments = [text for commands in lists for _, text in commands]
    if not any(is_check_command(text) for text in segments):
        return False, None
    last, programs = lists[-1], {_program(text) for text in segments}
    proof = complete and exit_code is not None and not programs & CONTROL_FLOW
    if not proof or any(joined not in ("", "&&") for joined, _ in last) or not any(is_check_command(text) for _, text in last):
        return True, None
    if exit_code == 0:
        return True, 0
    return True, exit_code if len(last) == 1 else None


def check_name(command: str) -> str:
    """The checks in a command's last list, the part its exit code speaks for: the check's identity, as
    written (spacing inside quotes names another file), and once shortened its name."""
    lists, _ = _command_lists(command)
    return " && ".join(text for _, text in (lists[-1] if lists else []) if is_check_command(text))


def check_key(command: str) -> str:
    """`cd repo && pytest` and `pytest` are the same check."""
    return re.sub(r"^cd \S+ *&& *", "", command)


def is_doc_path(path: str) -> bool:
    lowered = path.lower()
    return lowered.endswith(DOC_SUFFIXES) or "/docs/" in lowered or lowered.startswith("docs/")


def _canonical(path: str) -> str:
    """One spelling for macOS folders reachable under two names (/private/tmp is /tmp)."""
    path = posixpath.normpath(path)
    for alias, name in PATH_ALIASES:
        if path == alias or path.startswith(alias + "/"):
            return name + path[len(alias) :]
    return path


def _within(path: str, folder: str) -> bool:
    return path == folder or path.startswith(folder.rstrip("/") + "/")


def is_scratch_path(path: str, cwd: str, root: str = "") -> bool:
    """A throwaway file: under the project's own top-level `tmp/`, or a system temp file outside the project.

    `root` is the project root when something outside this module confirmed it; `cwd` alone may be a
    subfolder, so without `root` no tmp/ inside the project is exempt. A temp file outside the project is
    exempt only when the project is known not to live in a temp folder itself, where a sibling folder could
    still belong to it. Without `cwd` nothing is scratch.
    """
    if not cwd:
        return False
    cwd, root = _canonical(cwd), _canonical(root) if root else ""
    full = _canonical(posixpath.join(cwd, path))
    if root and _within(full, root):
        return full[len(root.rstrip("/")) + 1 :].startswith("tmp/")
    if not root and _within(full, cwd):
        return False
    return full.startswith(SCRATCH_ROOTS) and (bool(root) or not cwd.startswith(SCRATCH_ROOTS))


def code_paths(paths: list[str], cwd: str = "", root: str = "") -> list[str]:
    return [path for path in paths if not is_doc_path(path) and not is_scratch_path(path, cwd, root)]


def check_state(turn: Turn | None, cwd: str = "", root: str = "") -> str:
    """The check tag app.js shows: `failed` when a check's latest run failed, `unchecked` when code changed
    with no check after it, else "". Documentation and scratch edits never count, so a README fix raises no alarm."""
    if turn is None:
        return ""
    if any(check.exit_code not in (0, None) for check in turn.checks):
        return "failed"
    if code_paths(turn.files, cwd, root) and (not turn.checks or turn.edited_after_check):
        return "unchecked"
    return ""


def is_quiet(status: str, modified_ns: int, now: float | None = None) -> bool:
    """A working chat whose source has not changed for a while."""
    return status == "working" and (now or time.time()) - modified_ns / 1e9 > QUIET_SECONDS
