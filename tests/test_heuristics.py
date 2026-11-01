from __future__ import annotations

import pytest
from conftest import Parser

from yourturn.heuristics import check_name, check_result, check_state, is_check_command, parse_answer, parse_decisions, parse_recap
from yourturn.model import Check, Harness, SessionKey, Turn

UUID = "019a2b3c-4d5e-6f70-8192-a3b4c5d6e7f8"


def turn(files: list[str], checks: tuple[int | None, ...] = (), edited_after_check: bool = False) -> Turn:
    return Turn(1, files=files, checks=[Check("uv run pytest", code, "t") for code in checks],
                edited_after_check=edited_after_check)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        (turn([]), ""),
        (turn(["/w/repo/README.md", "/w/repo/NOTES.txt", "docs/guide.py"]), ""),
        (turn(["/w/repo/CHANGELOG.MD"]), ""),
        (turn(["/w/repo/app.py"]), "unchecked"),
        (turn(["/w/repo/app.py"], [0], edited_after_check=True), "unchecked"),
        (turn(["/w/repo/app.py"], [0]), ""),
        (turn(["/w/repo/README.md"], [1]), "failed"),
        (turn(["/w/repo/app.py"], [None]), ""),
    ],
)
def test_check_state(value: Turn | None, expected: str) -> None:
    assert check_state(value) == expected


@pytest.mark.parametrize(
    ("path", "cwd", "root", "expected"),
    [
        # Helper files outside a project that does not itself live in a temp folder.
        ("/tmp/probe.cjs", "/w/repo", "", ""),
        ("/private/tmp/probe.py", "/w/repo", "/w/repo", ""),
        ("/var/folders/ab/T/x/render.js", "/w/repo/src", "", ""),
        # The top-level tmp/ of a confirmed project root, however the path is written.
        ("/w/repo/tmp/render.py", "/w/repo", "/w/repo", ""),
        ("tmp/render.py", "/w/repo", "/w/repo", ""),
        ("../tmp/render.py", "/w/repo/src", "/w/repo", ""),
        ("/w/repo/./tmp/../tmp/render.py", "/w/repo/", "/w/repo", ""),
        ("/tmp/checkout/tmp/x.py", "/tmp/checkout", "/private/tmp/checkout", ""),
        # Code, whatever the folder names.
        ("/w/repo/src/tmp/module.py", "/w/repo", "/w/repo", "unchecked"),
        ("/w/repo/tmp.py", "/w/repo", "/w/repo", "unchecked"),
        ("/w/repo/tmpfiles/x.py", "/w/repo", "/w/repo", "unchecked"),
        ("/w/repo/tmp/../app.py", "/w/repo", "/w/repo", "unchecked"),
        ("/w/other/tmp/x.py", "/w/repo", "/w/repo", "unchecked"),
        # Without a confirmed root, cwd may be a subfolder: its tmp/ can be code.
        ("/w/repo/tmp/render.py", "/w/repo", "", "unchecked"),
        ("/w/repo/src/tmp/render.py", "/w/repo/src", "", "unchecked"),
        # A checkout under /tmp/ is a project like any other, under either name of that folder.
        ("/tmp/checkout/app.py", "/tmp/checkout", "", "unchecked"),
        ("/private/tmp/checkout/src/app.py", "/tmp/checkout", "", "unchecked"),
        ("/tmp/checkout/src/app.py", "/private/tmp/checkout", "", "unchecked"),
        ("/private/tmp/checkout/src/app.py", "/tmp/checkout", "/tmp/checkout", "unchecked"),
        ("/tmp/checkout/tests/test_app.py", "/tmp/checkout/src", "", "unchecked"),
        ("/tmp/checkout/tests/test_app.py", "/tmp/checkout/src", "/tmp/checkout", "unchecked"),
        ("/private/var/folders/ab/T/work/tests/test_app.py", "/var/folders/ab/T/work/src", "", "unchecked"),
        # Without a known working folder nothing is exempt.
        ("/tmp/probe.cjs", "", "", "unchecked"),
    ],
)
def test_scratch_edits_need_no_check(path: str, cwd: str, root: str, expected: str) -> None:
    assert check_state(turn([path]), cwd, root) == expected


def test_readme_edit_after_passing_check_keeps_it_passed() -> None:
    parser = Parser(UUID)

    def item(payload: dict) -> None:
        parser.feed({"timestamp": "t", "type": "event_msg", "payload": {"type": "item_completed", "item": payload}})

    item({"type": "FileChange", "changes": {"/w/repo/app.py": {}}})
    item({"type": "CommandExecution", "command": ["bash", "-lc", "uv run pytest -q"], "exit_code": 0})
    item({"type": "FileChange", "changes": {"/w/repo/README.md": {}}})
    assert check_state(parser.state.turns[-1]) == ""

    item({"type": "FileChange", "changes": {"/w/repo/app.py": {}}})
    assert check_state(parser.state.turns[-1]) == "unchecked"


@pytest.mark.parametrize(
    ("command", "expected"),
    [("uv run pytest -q", True), ("cd web && npm test", True), ("rg pytest", False), ("FOO=1 ruff check", True),
     ("node --test tests/", True), ("python3 -m unittest discover", True), ("python -m pytest -q", True),
     ("swift test", True), ("node server.js", False)],
)
def test_is_check_command(command: str, expected: bool) -> None:
    assert is_check_command(command) is expected


LONG_SETUP = "node --check src/codex_companion/static/app.js && git diff --check && " + "true && " * 20


@pytest.mark.parametrize(
    ("command", "exit_code", "expected"),
    [
        # A check proven to have run and passed: the last list is joined by `&&` only, and it exited 0.
        ("node --check app.js && git diff --check && make test", 0, (True, 0)),
        (LONG_SETUP + "make test", 0, (True, 0)),
        ("git status --short\nmake test", 0, (True, 0)),
        ("printf ready; make test", 0, (True, 0)),
        ("cd web && \\\n  npm test", 0, (True, 0)),
        ("uv run pytest -q 2>&1", 0, (True, 0)),
        ("cd web && uv run pytest -q", 0, (True, 0)),
        # A failure is the check's own when the check runs alone last, with nothing able to skip it.
        ("uv run pytest -q", 1, (True, 1)),
        ("pytest tests/test_a.py", 5, (True, 5)),
        ("printf ready; make test", 2, (True, 2)),
        ("printf ready\npytest tests/test_a.py", 1, (True, 1)),
        # A check is in the command, but the single exit code cannot be tied to it.
        ("cd /missing-folder && pytest", 1, (True, None)),
        ("cd web && npm test", 2, (True, None)),
        ("set -e; printf ready; make test", 2, (True, None)),
        ("exit 0; pytest", 0, (True, None)),
        ("exec true; pytest", 0, (True, None)),
        ("true && exit 0 && pytest", 0, (True, None)),
        ("FOO=1 exec true\npytest", 0, (True, None)),
        ("eval 'exit 0'; pytest", 0, (True, None)),
        # `set` changes how the shell runs, and sourced code can do anything, `exit` included.
        ("set -n; pytest", 0, (True, None)),
        ("set -euo pipefail; make test", 0, (True, None)),
        ("source /dev/stdin; pytest", 0, (True, None)),
        (". /dev/stdin; pytest", 0, (True, None)),
        ("source .venv/bin/activate && pytest", 1, (True, None)),
        (". ./env.sh\npytest", 1, (True, None)),
        ("pytest || true", 0, (True, None)),
        ("pytest; echo done", 0, (True, None)),
        ("true || pytest", 0, (True, None)),
        ("false && pytest", 1, (True, None)),
        ("uv run pytest -q 2>&1 | tail -5", 0, (True, None)),
        ("node --check app.js && make test", 2, (True, None)),
        ("uv run pytest -q", None, (True, None)),
        # Names of checks that are not commands that ran.
        ('echo "make test"', 0, (False, None)),
        ("rg pytest", 0, (False, None)),
        ("git diff --check", 0, (False, None)),
        ("git status  # then run pytest", 0, (False, None)),
        ("python - <<'PY'\nimport subprocess\nsubprocess.run(['pytest'])\nPY", 0, (False, None)),
        ("cat > notes.txt <<'EOF'\nmake test\nEOF\nls", 0, (False, None)),
        # Constructs this does not model are never proof.
        ("pytest $(ls tests)", 0, (False, None)),
        ("(cd web && npm test)", 0, (False, None)),
        ("if pytest; then echo ok; fi", 0, (False, None)),
        ("make serve & make test", 0, (False, None)),
        ("echo 'unterminated && make test", 0, (False, None)),
    ],
)
def test_check_result(command: str, exit_code: int | None, expected: tuple[bool, int | None]) -> None:
    assert check_result(command, exit_code) == expected


@pytest.mark.parametrize(
    ("command", "name"),
    [
        ("printf ready\npytest tests/test_a.py", "pytest tests/test_a.py"),
        ("cd web && npm test", "npm test"),
        ("node --check app.js && git diff --check && make test && uv run ruff check .", "make test && uv run ruff check ."),
        ("printf ready; make test   -k  fast", "make test   -k  fast"),
        ('pytest "tests/test  one.py"', 'pytest "tests/test  one.py"'),
    ],
)
def test_check_name_is_the_checks_that_ran_last(command: str, name: str) -> None:
    # The identity keeps the text as written; the title shown is shortened from it.
    assert check_name(command) == name


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

    examples = plugin_text("skills/your-turn-handoff/SKILL.md").split("## Examples", 1)[1]
    done, needs, choice = re.findall(r"```\n(.*?)```", examples, re.DOTALL)
    assert parse_answer(done) == ("The last page now shows its final row.", "none", "", True)
    assert parse_recap(done) == "Goal: correct pagination. Settled: the final row is visible. Open: nothing."
    assert parse_decisions(done) == []
    assert parse_answer(needs)[1:] == ("review", "the skipped-row log format in importer.py", True)
    assert parse_recap(needs) == "Goal: make imports tolerate bad rows. Settled: skip and log. Open: the log format."
    assert parse_decisions(needs) == [{"question": "Skip or abort on a malformed row?", "options": ["skip and log", "abort", "silent skip"],
                                       "chosen": "skip and log", "reason": "One bad row should not lose a whole import."}]
    assert parse_answer(choice)[1:] == ("decide", "Redis with a 60 s TTL, or an in-process LRU per worker?", True)
    assert parse_recap(choice) == "Goal: faster dashboard. Settled: queries are the bottleneck. Open: which cache."


def test_every_next_step_kind_is_documented_wherever_the_handoff_is_installed() -> None:
    from pathlib import Path

    from yourturn.heuristics import NEXT_KIND
    from yourturn.install import CLAUDE_BLOCK, plugin_text

    kinds = NEXT_KIND.pattern.split("(", 1)[1].split(")", 1)[0].split("|")
    snippet = (Path(__file__).resolve().parents[1] / "docs" / "agents-snippet.md").read_text(encoding="utf-8")
    for text in (plugin_text("skills/your-turn-handoff/SKILL.md"), CLAUDE_BLOCK, snippet):
        assert [kind for kind in kinds if f"{kind}:" not in text] == []


def test_every_handoff_copy_states_the_same_rules_and_its_own_edit_tool() -> None:
    from pathlib import Path

    from yourturn.install import CLAUDE_BLOCK, plugin_text, rule_text, skill_text

    snippet = (Path(__file__).resolve().parents[1] / "docs" / "agents-snippet.md").read_text(encoding="utf-8")
    skills = {"codex": plugin_text("skills/your-turn-handoff/SKILL.md"), "claude": skill_text("claude"), "cursor": skill_text("cursor")}
    cursor_rule = rule_text("cursor")
    rules = ["very top or the very bottom", "no prose between them", "in english", "exactly `", "optional suggestion",
             "joined with `&&`", "not from the shell"]
    for text in (*skills.values(), CLAUDE_BLOCK, cursor_rule, snippet):
        flat = " ".join(text.lower().split())
        assert [rule for rule in rules if rule not in flat] == []
    assert "Codex's native edit tool (`apply_patch`)" in skills["codex"]
    assert "Claude Code's native edit tool (`Edit` or `Write`)" in skills["claude"] and "`Edit` or `Write`" in CLAUDE_BLOCK
    cursor_tools = "`StrReplace`, `Write` or `ApplyPatch`"
    assert f"Cursor's native edit tool ({cursor_tools})" in skills["cursor"] and cursor_tools in cursor_rule
    assert all("apply_patch" not in text for text in (skills["claude"], skills["cursor"], CLAUDE_BLOCK, cursor_rule, snippet))


def test_backtick_wrapped_handoff_lines_still_parse() -> None:
    text = "`**Outcome:** Docs updated.`\n`**Next step:** review: the new section`\n`**Decision:** Where? -> README (over wiki). Easier to find.`"
    assert parse_answer(text) == ("Docs updated.", "review", "the new section", True)
    assert parse_decisions(text)[0]["chosen"] == "README"
    assert parse_decisions(text)[0]["reason"] == "Easier to find."


@pytest.mark.parametrize("step", ["No further action.", "No action needed", "none", "žiadny", "Žiadne.", "nič", "Nič!"])
def test_nothing_needed_phrasings_are_none(step: str) -> None:
    assert parse_answer(f"**Outcome:** Done.\n**Next step:** {step}")[1:3] == ("none", "")


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        ("Nič, len obnov stránku v prehliadači", ("do", "Nič, len obnov stránku v prehliadači")),
        ("nič nemeň a spusti make test", ("do", "nič nemeň a spusti make test")),
        ("run: make test", ("run", "make test")),
    ],
)
def test_slovak_none_does_not_swallow_an_instruction(step: str, expected: tuple[str, str]) -> None:
    assert parse_answer(f"**Outcome:** Hotovo.\n**Ďalší krok:** {step}")[1:3] == expected


def test_handoff_block_at_the_top_or_the_bottom_parses_the_same() -> None:
    block = "**Outcome:** Opravené zobrazenie.\n**Next step:** none"
    body = "Upravil som `app.js` a pridal test.\n\nMôžeš to pushnúť, keď budeš chcieť."
    assert parse_answer(f"{block}\n\n{body}") == parse_answer(f"{body}\n\n{block}") == ("Opravené zobrazenie.", "none", "", True)


def test_handoff_lines_inside_code_blocks_are_ignored() -> None:
    text = "**Outcome:** Docs updated.\n**Next step:** none\n\n```\n**Next step:** review: the example\n**Recap:** example\n```"
    assert parse_answer(text) == ("Docs updated.", "none", "", True)
    assert parse_recap(text) == ""


def test_markdown_links_keep_only_their_text() -> None:
    assert parse_answer("Updated [routes/web.md](routes/web.md) and ![shot](docs/a.png).")[0] == "Updated routes/web.md and shot."
