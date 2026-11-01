from types import SimpleNamespace

import pytest

from yourturn.engine import SessionHub, TurnFolder
from yourturn.harness.base import HarnessAdapter
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
        assert row["activity_summary"] == "Bash: make test"
        folder.pending_tool = ""
        assert SessionHub([])._json(tracked, detail=False)["activity_summary"] == "Inspecting source"
    else:
        assert "activity_summary" not in row
