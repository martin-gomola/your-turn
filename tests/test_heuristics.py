from __future__ import annotations

import pytest

from yourturn.heuristics import check_state, check_status, is_check_command
from yourturn.model import Check, CheckState, Harness, SessionKey, Turn
from yourturn.rollout import RolloutParser

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
    parser = RolloutParser(UUID)

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
