"""The inbox as app.js files it, from rows the adapters and engine really produce."""

from __future__ import annotations

import json
import shutil
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

import test_claude_adapter as cl
import test_cursor_adapter as cu
from yourturn.engine import SessionHub

CONSUMER = Path(__file__).with_name("inbox_consumer.mjs")
CHATS = {
    "unflagged": "9f1c2b3a-0000-4000-8000-0000000000a1",
    "error": "9f1c2b3a-0000-4000-8000-0000000000a2",
    "answer": "9f1c2b3a-0000-4000-8000-0000000000a3",
}
APPROVAL, HEADER_ONLY = "9f1c2b3a-4d5e-4f60-8a9b-0c1d2e3f4ab1", "9f1c2b3a-4d5e-4f60-8a9b-0c1d2e3f4ab2"


def _rows(tmp_path: Path) -> list[dict[str, Any]]:
    claude, cursor, user_dir, codex = tmp_path / "claude", tmp_path / "cursor", tmp_path / "User", tmp_path / "codex"
    (codex / "sessions").mkdir(parents=True)
    (cursor / "projects").mkdir(parents=True)
    go = cl.user(1, "Fix the bug")
    last = {
        "unflagged": cl.synthetic(2, cl.LOGIN),
        "error": cl.synthetic(2, cl.LOGIN, isApiErrorMessage=True, error="authentication_failed"),
        "answer": cl._text(2, "**Outcome:** Fixed.\n**Next step:** none", "m1"),
    }
    for name, sid in CHATS.items():
        cl._write(claude, [{**record, "sessionId": sid} for record in (go, last[name])], sid=sid)
    header = {**cu._header("Approve me", pending=True), "composerId": APPROVAL}
    cu._database(user_dir, [(APPROVAL, 0, 0, header), (HEADER_ONLY, 0, 0, {**cu._header("No content"), "composerId": HEADER_ONLY,
                                                                              "latestConversationSummary": {"summary": {"summary": "Edited README.md"}}})])
    hub = SessionHub.for_codex_home(codex, scan_ttl=0, claude_home=claude, cursor_home=cursor, cursor_user_dir=user_dir)
    return hub.inbox_dicts()


@pytest.mark.skipif(shutil.which("node") is None, reason="needs Node")
def test_uncertain_end_is_not_a_new_result_and_only_missing_content_is_called_missing(tmp_path: Path) -> None:
    rows = _rows(tmp_path)
    # An hour after the turns ended: well inside the window for new results.
    now = datetime.fromisoformat(cl._ts(2).replace("Z", "+00:00")).timestamp() * 1000 + 3600_000
    run = subprocess.run(["node", str(CONSUMER)], input=json.dumps({"rows": rows, "now": now}), capture_output=True, text=True, check=True)
    filed = {row["key"]: row for row in json.loads(run.stdout)}
    by_id = {f"claude:{sid}": name for name, sid in CHATS.items()} | {f"cursor:{APPROVAL}": "approval", f"cursor:{HEADER_ONLY}": "header only"}
    sections = {by_id[key]: (row["section"], row["state"]) for key, row in filed.items()}
    assert sections == {
        "unflagged": ("earlier", "unknown"),  # Ended without saying how, and without a result.
        "error": ("earlier", "interrupted"),
        "answer": ("new", "done"),
        "approval": ("waiting", "waiting"),  # The explicit approval still needs you.
        "header only": ("earlier", "unknown"),
    }
    assert Counter(section for section, _ in sections.values()) == {"earlier": 3, "new": 1, "waiting": 1}
    notes = {by_id[key]: row["tooltip"] for key, row in filed.items() if row["tooltip"]}
    assert notes["header only"].startswith("Cursor keeps no local record of this chat’s messages")
    assert notes["unflagged"] == "The last turn ended without a recorded result or reason, so whether it finished is unknown."
