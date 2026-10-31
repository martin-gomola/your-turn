from __future__ import annotations

import pytest
from conftest import Parser

from yourturn.heuristics import check_state, check_status, is_check_command, parse_answer, parse_decisions, parse_recap
from yourturn.model import Check, CheckState, Harness, SessionKey, Turn

UUID = "019a2b3c-4d5e-6f70-8192-a3b4c5d6e7f8"


def turn(files: list[str], checks: tuple[int | None, ...] = (), edited_after_check: bool = False) -> Turn:
    return Turn(1, files=files, checks=[Check("uv run pytest", code, "t") for code in checks],
                edited_after_check=edited_after_check)


@pytest.mark.parametrize(
    ("value", "expected", "legacy"),
    [
        (None, CheckState.NOT_APPLICABLE, ""),
        (turn([]), CheckState.NOT_APPLICABLE, ""),
        (turn(["/w/repo/README.md", "/w/repo/NOTES.txt", "docs/guide.py"]), CheckState.NOT_APPLICABLE, ""),
        (turn(["/w/repo/CHANGELOG.MD"]), CheckState.NOT_APPLICABLE, ""),
        (turn(["/w/repo/app.py"]), CheckState.UNCHECKED, "unchecked"),
        (turn(["/w/repo/app.py"], [0], edited_after_check=True), CheckState.UNCHECKED, "unchecked"),
        (turn(["/w/repo/app.py"], [0]), CheckState.PASSED, ""),
        (turn(["/w/repo/README.md"], [1]), CheckState.FAILED, "failed"),
        (turn(["/w/repo/app.py"], [None]), CheckState.UNKNOWN, ""),
    ],
)
def test_check_status(value: Turn | None, expected: CheckState, legacy: str) -> None:
    assert check_status(value) is expected
    assert check_state(value) == legacy


def test_readme_edit_after_passing_check_keeps_it_passed() -> None:
    parser = Parser(UUID)

    def item(payload: dict) -> None:
        parser.feed({"timestamp": "t", "type": "event_msg", "payload": {"type": "item_completed", "item": payload}})

    item({"type": "FileChange", "changes": {"/w/repo/app.py": {}}})
    item({"type": "CommandExecution", "command": ["bash", "-lc", "uv run pytest -q"], "exit_code": 0})
    item({"type": "FileChange", "changes": {"/w/repo/README.md": {}}})
    assert check_status(parser.state.turns[-1]) is CheckState.PASSED

    item({"type": "FileChange", "changes": {"/w/repo/app.py": {}}})
    assert check_status(parser.state.turns[-1]) is CheckState.UNCHECKED


@pytest.mark.parametrize(
    ("command", "expected"),
    [("uv run pytest -q", True), ("cd web && npm test", True), ("rg pytest", False), ("FOO=1 ruff check", True)],
)
def test_is_check_command(command: str, expected: bool) -> None:
    assert is_check_command(command) is expected


@pytest.mark.parametrize(
    ("raw", "harness", "native_id"),
    [
        (UUID, Harness.CODEX, UUID),
        (f"codex:{UUID}", Harness.CODEX, UUID),
        ("claude:abc", Harness.CLAUDE, "abc"),
        ("cursor:state.vscdb#composer:1234:5", Harness.CURSOR, "state.vscdb#composer:1234:5"),
    ],
)
def test_session_key_parse(raw: str, harness: Harness, native_id: str) -> None:
    key = SessionKey.parse(raw)
    assert (key.harness, key.native_id) == (harness, native_id)
    if ":" in raw:
        assert str(key) == raw


@pytest.mark.parametrize("raw", ["", "not-a-uuid", "vim:abc", "claude:"])
def test_session_key_rejects(raw: str) -> None:
    with pytest.raises(ValueError):
        SessionKey.parse(raw)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("**Decision:** Patch or rewrite the parser? -> patch (over rewrite). Smaller diff, same tests.",
         ("Patch or rewrite the parser?", ["patch", "rewrite"], "patch", "Smaller diff, same tests.")),
        ("Decision: Which store → SQLite (over Postgres, a JSON file or Redis). No server to run.",
         ("Which store?", ["SQLite", "Postgres", "a JSON file", "Redis"], "SQLite", "No server to run.")),
        ("- Decision: Cache the index? -> no. Reads are cheap.", ("Cache the index?", ["no"], "no", "Reads are cheap.")),
        ("Decision: Pin uv -> 0.9.2", ("Pin uv?", ["0.9.2"], "0.9.2", "")),
        ("decision: `fetch` or `httpx`? -> `httpx` (over `fetch`)", ("fetch or httpx?", ["httpx", "fetch"], "httpx", "")),
    ],
)
def test_decision_lines_parse(line: str, expected: tuple[str, list[str], str, str]) -> None:
    (decision,) = parse_decisions(f"**Outcome:** Done.\n**Next step:** none\n{line}\n\nDetails.")
    assert (decision["question"], decision["options"], decision["chosen"], decision["reason"]) == expected


def test_several_decisions_and_lines_that_are_not_decisions() -> None:
    text = (
        "**Outcome:** Shipped.\n**Next step:** none\n"
        "**Decision:** Library? -> httpx (over requests). Async.\n"
        "**Decision:** Retry? → yes. Flaky network.\n"
        "The decision: was easy -> not a line of its own.\n"
        "Decision: no arrow here\n"
        "Decision: Empty? -> \n"
        "```\nDecision: in code -> ignored\n```\n"
    )
    assert [d["chosen"] for d in parse_decisions(text)] == ["httpx", "yes"]
    # Decision lines never become the outcome or the next step.
    assert parse_answer(text)[:3] == ("Shipped.", "none", "")


def test_skill_examples_parse_as_documented() -> None:
    import re

    from yourturn.install import plugin_text

    done, needs = re.findall(r"## Examples.*?```\n(.*?)```.*?```\n(.*?)```", plugin_text("skills/your-turn-handoff/SKILL.md"), re.DOTALL)[0]
    assert parse_answer(done) == ("The last page now shows its final row.", "none", "", True)
    assert parse_answer(needs)[1:] == ("review", "the skipped-row log format in importer.py", True)
    assert parse_decisions(needs) == [{"question": "Skip or abort on a malformed row?", "options": ["skip and log", "abort", "silent skip"],
                                       "chosen": "skip and log", "reason": "One bad row should not lose a whole import."}]


def test_handoff_lines_inside_code_blocks_are_ignored() -> None:
    text = "**Outcome:** Docs updated.\n**Next step:** none\n\n```\n**Next step:** review: the example\n**Recap:** example\n```"
    assert parse_answer(text) == ("Docs updated.", "none", "", True)
    assert parse_recap(text) == ""
