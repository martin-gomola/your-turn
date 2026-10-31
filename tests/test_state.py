"""Seen results and dismissed reminders are kept server-side, so every browser shows the same inbox."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import OTHER, THREAD
from fastapi.testclient import TestClient

from yourturn.app import create_app

JSON = {"Content-Type": "application/json"}


def test_marks_are_shared_merged_pruned_and_streamed(codex_home: Path, tmp_path: Path) -> None:
    path = tmp_path / "state" / "state.json"
    polls = iter([False, True])
    gone = "0d3e1000-0000-7000-8000-0000000000ff"
    path.parent.mkdir()
    path.write_text(json.dumps({"seen": {f"codex:{gone}": "2026-10-01T00:00:00Z"}}))
    app = TestClient(create_app(codex_home, state_path=path, should_stop=lambda: next(polls, True), poll_seconds=0),
                     base_url="http://127.0.0.1")

    assert app.post("/api/state", headers=JSON, json={"seen": {THREAD: "2026-10-27T10:03:12Z"},
                                                       "dismissed": {f"codex:{OTHER}": "key-1"}}).status_code == 204
    # A stale tab cannot mark a newer result unread; null restores a reminder.
    app.post("/api/state", headers=JSON, json={"seen": {f"codex:{THREAD}": "2026-10-27T09:00:00Z"}, "dismissed": {OTHER: None}})
    saved = json.loads(path.read_text())
    assert saved == {"dismissed": {}, "seen": {f"codex:{THREAD}": "2026-10-27T10:03:12Z"}}, "the chat no longer in the inbox is dropped"

    with app.stream("GET", "/api/stream") as response:
        head, data = response.read().decode().split("\n", 2)[:2]
    assert head == "event: state" and json.loads(data.removeprefix("data: "))["seen"] == saved["seen"]


def test_only_this_page_can_write(codex_home: Path, tmp_path: Path) -> None:
    app = TestClient(create_app(codex_home, state_path=tmp_path / "state.json"), base_url="http://127.0.0.1")
    body = {"seen": {THREAD: "x"}}
    assert app.post("/api/state", content=json.dumps(body), headers={"Content-Type": "text/plain"}).status_code == 403
    assert app.post("/api/state", json=body, headers={**JSON, "Origin": "https://evil.example"}).status_code == 403
    assert app.post("/api/state", json={"seen": {THREAD: 1}}, headers=JSON).status_code == 400
    assert app.post("/api/state", json={"seen": {"not-a-key": "x"}}, headers=JSON).status_code == 400
    assert not (tmp_path / "state.json").exists()
    assert app.post("/api/state", json=body, headers={**JSON, "Origin": "http://127.0.0.1:8787"}).status_code == 204
