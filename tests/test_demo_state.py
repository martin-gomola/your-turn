import json
import urllib.request

from scripts.readme_screenshots import demo_chats, demo_server


def test_demo_server_never_rewrites_user_inbox_state(tmp_path, monkeypatch):
    # Redirect the child's default state to a sentinel, so this regression cannot touch real preferences.
    sentinel = tmp_path / "user-state.json"
    saved = {"seen": {}, "dismissed": {"codex:existing-chat": "dismissed-request"}}
    sentinel.write_text(json.dumps(saved))
    bootstrap = tmp_path / "bootstrap"
    bootstrap.mkdir()
    (bootstrap / "sitecustomize.py").write_text(
        "from pathlib import Path\nfrom yourturn.state import InboxState\n"
        f"InboxState.__init__.__defaults__ = (Path({str(sentinel)!r}),)\n"
    )
    monkeypatch.setenv("PYTHONPATH", str(bootstrap))
    with demo_server(demo_chats()) as (base, _):
        with urllib.request.urlopen(base + "/api/inbox") as response:
            row = next(row for row in json.load(response) if row["needs_you"] and row["attention_key"])
        request = urllib.request.Request(base + "/api/state", method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"dismissed": {row["key"]: row["attention_key"]}}).encode())
        with urllib.request.urlopen(request) as response:
            assert response.status == 204
        assert json.loads(sentinel.read_text()) == saved
