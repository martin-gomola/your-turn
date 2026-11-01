from types import SimpleNamespace

import pytest

from yourturn.engine import SessionHub, TurnFolder
from yourturn.harness.base import CommandRun, HarnessAdapter, TurnStarted
from yourturn.heuristics import command_caption
from yourturn.model import Capabilities, Decision, Handoff, SessionRef, Turn


@pytest.mark.parametrize(("harness", "live"), [("codex", True), ("claude", True), ("cursor", False)])
@pytest.mark.parametrize("status", ["working", "done"])
def test_inbox_activity_and_search_fields(harness, live, status):
    class Adapter(HarnessAdapter):
        capabilities = Capabilities(live_activity=live)

        def handoff(self, ref, cwd):
            return Handoff()

    ref = SessionRef(harness=harness, session_id="session")
    folder = TurnFolder(ref)
    folder.turns.append(Turn(index=1, status=status, files=["src/app.py"], recap="OAuth fixed"))
    folder.status = status
    folder.activity = "Inspecting source"
    folder.pending_tool = "Bash: make test"
    folder.decisions.append(Decision("", "answer", "Which store?", ["SQLite"], "SQLite"))
    tracked = SimpleNamespace(folder=folder, adapter=Adapter(), ref=ref, quiet=lambda *args: False)
    row = SessionHub([])._json(tracked, detail=False)
    assert row["recap"] == "OAuth fixed"
    assert row["changed_files"] == ["src/app.py"]
    assert row["decisions"][0]["chosen"] == "SQLite"
    if live and status == "working":
        assert row["activity_summary"] == "make test"
        folder.pending_tool = ""
        assert SessionHub([])._json(tracked, detail=False)["activity_summary"] == "Inspecting source"
    else:
        assert "activity_summary" not in row


@pytest.mark.parametrize(("command", "caption"), [
    ("uv run pytest -q && node --test > tmp/results.log && tail -8 tmp/results.log", "pytest && node --test"),
    ("cd web\nuv run pytest -q && node --test && ruff check .", "pytest && node --test"),
    ("pytest tests/a.py && pytest tests/b.py", "pytest"),
    ("echo 'pytest && node --test'", "Shell command"),
    ("cd web && git diff --stat", "git diff"),
    ("uv run python -m example.inspect --long-option data.json", "example.inspect"),
    ("uv run python scripts/generate.py --output tmp/generated.json", "python"),
])
def test_command_caption(command, caption):
    assert command_caption(command) == caption


def test_activity_caption_uses_full_command_without_changing_recorded_activity():
    folder = TurnFolder(SessionRef(harness="codex", session_id="session"))
    folder.fold(TurnStarted())
    full = "cd web && " + "true && " * 30 + "uv run pytest -q && node --test"
    folder.fold(CommandRun(command=full[:120], full_command=full, exit_code=0))
    assert folder.activity_summary == "pytest && node --test"
    assert folder.activity == full[:120]
