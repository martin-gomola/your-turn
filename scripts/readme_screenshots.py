"""Render README screenshots from made-up Codex, Claude Code and Cursor homes, so no real chat content is captured.

Run with `make screenshots`. Needs Google Chrome; Playwright comes from `uvx --with playwright`.
"""

from __future__ import annotations

import base64
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "images"
NOW = datetime.now(UTC)


def at(minutes_ago: float) -> str:
    return (NOW - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class Chat:
    def __init__(self, number: int, title: str, project: str, started: float) -> None:
        self.id = f"0d3e{number:04x}-0000-7000-8000-{number:012x}"
        self.title, self.project, self.clock, self.turn = title, project, started, 0
        self.records: list[dict] = [
            {"timestamp": at(started), "type": "session_meta", "payload": {
                "id": self.id, "cwd": f"/workspace/{project}", "timestamp": at(started), "source": "vscode",
                "model_provider": "openai", "cli_version": "0.80.0", "git": {"branch": "main"}}},
            {"timestamp": at(started), "type": "turn_context", "payload": {"model": "gpt-5.5", "effort": "medium"}},
        ]

    def _add(self, record_type: str, payload: dict) -> None:
        self.clock -= 0.5
        self.records.append({"timestamp": at(self.clock), "type": record_type, "payload": payload})

    def _item(self, body: dict) -> None:
        self._add("event_msg", {"type": "item_completed", "thread_id": self.id, "turn_id": f"t{self.turn}", "item": body})

    def ask(self, prompt: str) -> Chat:
        self.turn += 1
        self._add("event_msg", {"type": "task_started", "turn_id": f"t{self.turn}"})
        self._item({"type": "UserMessage", "content": [{"type": "text", "text": prompt}]})
        return self

    def reply(self, question: str, answer: str) -> Chat:
        replies = json.dumps([{"question": question, "answer": answer}])
        return self.ask(f"<send_user_message_question_reply>{replies}</send_user_message_question_reply>")

    def think(self, summary: str) -> Chat:
        self._item({"type": "Reasoning", "summary_text": [summary]})
        return self

    def run(self, command: str, exit_code: int = 0) -> Chat:
        self._item({"type": "CommandExecution", "command": ["/bin/zsh", "-lc", command], "exit_code": exit_code})
        return self

    def edit(self, *paths: str) -> Chat:
        changes = {f"/workspace/{self.project}/{path}": {"type": "update"} for path in paths}
        self._item({"type": "FileChange", "changes": changes})
        return self

    def decide(self, question: str, options: list[str], chosen: str, reason: str) -> Chat:
        arguments = {"question": question, "options": options, "chosen": chosen, "reason": reason}
        self._item({"type": "McpToolCall", "server": "your-turn", "tool": "log_decision",
                    "status": "completed", "arguments": arguments})
        return self

    def answer(self, text: str, question: dict | None = None) -> Chat:
        body = {"type": "AgentMessage", "phase": "final_answer", "content": [{"type": "Text", "text": text}]}
        if question:
            body["questions"] = [question]
        self._item(body)
        self._add("event_msg", {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": 182_000, "cached_input_tokens": 120_000, "output_tokens": 9_400,
                                  "reasoning_output_tokens": 3_100, "total_tokens": 191_400},
            "last_token_usage": {"input_tokens": 61_000, "output_tokens": 1_800, "total_tokens": 62_800},
            "model_context_window": 258_000}})
        self._add("event_msg", {"type": "task_complete", "turn_id": f"t{self.turn}", "duration_ms": 184_000})
        return self

    def write(self, home: Path, held: int = 0) -> Path:
        """Write the session file, holding back the last `held` records for `append_held`."""
        folder = home / "sessions" / NOW.strftime("%Y/%m/%d")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"rollout-{NOW.strftime('%Y-%m-%dT%H-%M-%S')}-{self.id}.jsonl"
        records = self.records[:len(self.records) - held]
        path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
        mtime = (NOW - timedelta(minutes=self.clock)).timestamp()
        if not held:
            os.utime(path, (mtime, mtime))
        return path

    def append_held(self, path: Path, held: int) -> None:
        with path.open("a", encoding="utf-8") as file:
            file.write("".join(json.dumps(record) + "\n" for record in self.records[-held:]))


# Chat.answer adds the final message, a token count and task_complete.
ANSWER_RECORDS = 3


def _touch(path: Path, minutes_ago: float) -> None:
    stamp = (NOW - timedelta(minutes=minutes_ago)).timestamp()
    os.utime(path, (stamp, stamp))


class ClaudeChat:
    """A made-up Claude Code transcript (`<home>/projects/<slug>/<id>.jsonl`)."""

    def __init__(self, number: int, title: str, project: str, started: float) -> None:
        self.id = f"c1a0{number:04x}-0000-4000-8000-{number:012x}"
        self.title, self.project, self.clock, self.tools = title, project, started, 0
        self.records: list[dict] = [{"type": "custom-title", "customTitle": title, "sessionId": self.id}]

    def _add(self, kind: str, **fields: object) -> None:
        self.clock -= 0.5
        self.records.append({"type": kind, "timestamp": at(self.clock), "sessionId": self.id, "cwd": f"/workspace/{self.project}",
                             "gitBranch": "main", "version": "2.1.0", "isSidechain": False, **fields})

    def _assistant(self, block: dict, stop: str = "tool_use") -> None:
        self.tools += 1
        self._add("assistant", effort="high", message={
            "model": "claude-opus-4-5", "id": f"msg{self.tools}", "role": "assistant", "content": [block], "stop_reason": stop,
            "usage": {"input_tokens": 1_200, "cache_creation_input_tokens": 2_400, "cache_read_input_tokens": 38_000, "output_tokens": 900}})

    def _tool(self, name: str, arguments: dict, result: str | None = "", error: bool = False) -> ClaudeChat:
        self._assistant({"type": "tool_use", "id": f"tool{self.tools}", "name": name, "input": arguments})
        if result is not None:
            self._add("user", message={"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"tool{self.tools - 1}", "content": result, "is_error": error}]})
        return self

    def ask(self, prompt: str) -> ClaudeChat:
        self._add("user", message={"role": "user", "content": prompt})
        return self

    def think(self, text: str) -> ClaudeChat:
        self._assistant({"type": "thinking", "thinking": text, "signature": "demo"})
        return self

    def run(self, command: str, error: bool = False) -> ClaudeChat:
        return self._tool("Bash", {"command": command, "description": "Run checks"}, "FAILED" if error else "ok", error)

    def edit(self, *paths: str) -> ClaudeChat:
        for path in paths:
            self._tool("Edit", {"file_path": f"/workspace/{self.project}/{path}", "old_string": "a", "new_string": "b"})
        return self

    def question(self, title: str, options: list[str]) -> ClaudeChat:
        """AskUserQuestion with no answer yet: the chat waits on the user."""
        return self._tool("AskUserQuestion", {"questions": [{"question": title, "header": "Choice", "multiSelect": False,
                                                             "options": [{"label": o, "description": o} for o in options]}]}, None)

    def write(self, home: Path) -> Path:
        folder = home / "projects" / f"-workspace-{self.project}"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{self.id}.jsonl"
        path.write_text("".join(json.dumps(record) + "\n" for record in self.records), encoding="utf-8")
        _touch(path, self.clock)
        return path


class CursorChat:
    """A made-up Cursor agent transcript plus its `composerHeaders` row."""

    def __init__(self, number: int, title: str, project: str, started: float, *, approval: bool = False) -> None:
        self.id = f"c0a5{number:04x}-0000-4000-8000-{number:012x}"
        self.title, self.project, self.started, self.approval = title, project, started, approval
        self.records: list[dict] = []

    def ask(self, prompt: str) -> CursorChat:
        local = (NOW - timedelta(minutes=self.started)).strftime("%A, %b %d, %Y, %I:%M %p")
        self.records.append({"role": "user", "message": {"content": [
            {"type": "text", "text": f"<timestamp>{local} (UTC+0)</timestamp>\n<user_query>\n{prompt}\n</user_query>"}]}})
        return self

    def say(self, text: str, *tools: tuple[str, dict]) -> CursorChat:
        content = [{"type": "text", "text": text}] + [{"type": "tool_use", "name": name, "input": args} for name, args in tools]
        self.records.append({"role": "assistant", "message": {"content": content}})
        return self

    def write(self, home: Path, database: sqlite3.Connection, minutes_ago: float) -> Path:
        folder = home / "projects" / f"workspace-{self.project}" / "agent-transcripts" / self.id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{self.id}.jsonl"
        path.write_text("".join(json.dumps(record) + "\n" for record in self.records), encoding="utf-8")
        _touch(path, minutes_ago)
        millis = lambda minutes: int((NOW - timedelta(minutes=minutes)).timestamp() * 1000)  # noqa: E731
        cwd = f"/workspace/{self.project}"
        value = {"composerId": self.id, "name": self.title, "createdAt": millis(self.started), "lastUpdatedAt": millis(minutes_ago),
                 "hasBlockingPendingActions": self.approval, "workspaceIdentifier": {"id": "demo", "uri": {"fsPath": cwd, "scheme": "file"}}}
        database.execute("INSERT INTO composerHeaders VALUES (?, 'demo', ?, ?, 0, 0, ?)",
                         (self.id, value["createdAt"], value["lastUpdatedAt"], json.dumps(value)))
        return path


def demo_other_chats() -> tuple[list[ClaudeChat], list[tuple[CursorChat, float]]]:
    """One Claude Code chat asking a question, one working, and a Cursor chat blocked on an approval."""
    claude = [
        ClaudeChat(1, "Fix recipe import", "recipe-box", 60)
        .ask("Recipe import fails on the new CSV header.")
        .think("Comparing the old and new header rows")
        .edit("app/recipes/importer.py", "tests/test_importer.py")
        .run("uv run pytest -q tests/test_importer.py")
        .question("Rows with an unknown unit: skip them, or import them without a unit?", ["Skip the row", "Import without unit"]),
        ClaudeChat(2, "Add hourly forecast chart", "weather-widget", 3)
        .ask("Add an hourly chart to the forecast card.")
        .think("Reading the forecast card layout")
        .edit("frontend/src/ForecastCard.tsx")
        .run("npm test -- ForecastCard"),
    ]
    cursor = [
        (CursorChat(1, "Upgrade Vite to v6", "weather-widget", 20, approval=True)
         .ask("Upgrade Vite to v6 and fix anything that breaks.")
         .say("Updating the config for Vite 6.", ("StrReplace", {"path": "/workspace/weather-widget/frontend/vite.config.ts",
                                                                  "old_string": "a", "new_string": "b"}))
         .say("Installing the new version.", ("Shell", {"command": "npm install vite@6", "description": "Upgrade Vite"})), 1),
    ]
    return claude, cursor


def demo_chats(reminders_started: float = 40) -> list[Chat]:
    return [
        Chat(1, "Add watering reminders", "garden-planner", reminders_started)
        .ask("Add watering reminders to the plant detail screen.")
        .think("**Checking how plant schedules are stored**")
        .edit("frontend/src/features/plants/Reminders.tsx", "backend/api/reminders.py")
        .run("make check")
        .answer("**Outcome:** Reminders work on the plant screen; storage is the open question.\n\n"
                "**Next step:** answer: choose where reminders are stored.",
                {"title": "Store reminders on this device only, or sync them to the server?",
                 "options": ["This device only", "Sync to server"]}),
        Chat(2, "Fix plant search ranking", "garden-planner", 95)
        .ask("Search for 'basil' shows thyme first. Fix the ranking.")
        .think("**Comparing prefix and fuzzy scores**")
        .decide("How should exact names rank?", ["Boost exact prefix", "Tune fuzzy threshold"],
                "Boost exact prefix", "Smaller change; keeps typo tolerance")
        .edit("backend/search/ranking.py", "backend/tests/test_ranking.py")
        .run("uv run pytest -q backend/tests/test_ranking.py", 1)
        .edit("backend/search/ranking.py")
        .run("uv run pytest -q")
        .answer("**Outcome:** Exact name matches now rank first; all 48 tests pass.\n\n"
                "**Next step:** answer: choose how ties are ordered.",
                {"title": "When two plants score the same, order them by popularity or alphabetically?",
                 "options": ["By popularity", "Alphabetically"]})
        .reply("When two plants score the same, order them by popularity or alphabetically?", "By popularity")
        .think("**Adding a popularity tie-break**")
        .edit("backend/search/tiebreak.py", "backend/search/ranking.py", "docs/SEARCH.md")
        .run("uv run pytest -q")
        .answer("**Outcome:** Ties now fall back to popularity; all 51 tests pass.\n\n"
                "**Recap:** Search ranks exact name prefixes first and breaks ties by popularity, "
                "with tests for both and the rules written up in docs/SEARCH.md.\n\n"
                "**Next step:** none."),
        Chat(5, "Write offline sync guide", "weather-widget", 150)
        .ask("Document how the outbox handles conflicts.")
        .edit("docs/SYNC.md")
        .answer("**Outcome:** Added docs/SYNC.md with the conflict flow.\n\n**Next step:** none."),
    ]


CODEX_WINDOW = """<!doctype html><html><head><style>
* { box-sizing: border-box; margin: 0; }
body { font: 13px/1.5 -apple-system, system-ui, sans-serif; color: #1d1d1f; background: #e9ecef;
       padding: 28px; height: 100vh; }
.window { display: flex; height: 100%; background: #fff; border-radius: 12px; overflow: hidden;
          box-shadow: 0 0 0 1px #0002, 0 18px 50px #0003; }
.side { width: 210px; background: #f6f6f7; border-right: 1px solid #e4e4e7; padding: 14px 12px; color: #52525b; }
.lights { display: flex; gap: 8px; margin-bottom: 22px; }
.lights i { width: 12px; height: 12px; border-radius: 50%; }
.side b { display: block; color: #1d1d1f; font-size: 15px; margin-bottom: 12px; }
.side p { padding: 5px 8px; border-radius: 6px; }
.side .on { background: #e4e4e7; color: #1d1d1f; }
.side h6 { font: 600 11px/1 system-ui; color: #a1a1aa; margin: 16px 8px 6px; }
.chat { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.bar { height: 44px; border-bottom: 1px solid #e4e4e7; display: flex; align-items: center; padding: 0 18px; font-weight: 600; }
.log { flex: 1; padding: 22px 28px; display: flex; flex-direction: column; gap: 14px; overflow: hidden; }
.me { align-self: flex-end; background: #f1f1f3; padding: 8px 12px; border-radius: 14px; max-width: 70%; }
.step { color: #71717a; font-size: 12px; }
.ask { border: 1px solid #e4e4e7; border-radius: 10px; padding: 12px; }
.ask span { display: inline-block; margin: 8px 6px 0 0; padding: 4px 10px; border: 1px solid #d4d4d8; border-radius: 6px; }
.compose { margin: 0 22px 18px; border: 1px solid #e4e4e7; border-radius: 14px; padding: 12px 14px; color: #a1a1aa;
           display: flex; justify-content: space-between; }
.pane { width: 420px; border-left: 1px solid #e4e4e7; display: flex; flex-direction: column; }
.url { height: 44px; display: flex; align-items: center; gap: 10px; padding: 0 12px; border-bottom: 1px solid #e4e4e7; color: #a1a1aa; }
.url div { flex: 1; background: #f1f1f3; border-radius: 6px; padding: 3px 10px; color: #52525b; font-size: 12px;
           white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.pane img { width: 420px; display: block; }
</style></head><body><div class="window">
<div class="side"><div class="lights"><i style="background:#ff5f57"></i><i style="background:#febc2e"></i><i style="background:#28c840"></i></div>
<b>Codex</b><p>New chat</p><h6>Projects</h6><p>garden-planner</p><p>weather-widget</p>
<h6>Recents</h6><p class="on">Add watering reminders</p><p>Fix plant search ranking</p><p>Write offline sync guide</p></div>
<div class="chat"><div class="bar">Add watering reminders</div><div class="log">
<div class="me">Add watering reminders to the plant detail screen.</div>
<div class="step">Edited 2 files · Ran make check</div>
<div><b>Outcome:</b> Reminders work on the plant screen; storage is the open question.</div>
<div><b>Next step:</b> answer: choose where reminders are stored.</div>
<div class="ask">Store reminders on this device only, or sync them to the server?<br><span>This device only</span><span>Sync to server</span></div>
</div><div class="compose"><span>Ask for follow-up changes</span><span>GPT-5.5 Medium</span></div></div>
<div class="pane"><div class="url">&larr; &rarr; &#8635;<div>127.0.0.1:8787/?thread=THREAD</div></div><img src="data:image/png;base64,SHOT"></div>
</div></body></html>"""


def demo_gif(browser, base: str, chat: Chat, path: Path) -> None:
    """Film a chat moving into Needs you when its question arrives, then opening it."""
    page = browser.new_page(viewport={"width": 1280, "height": 800}, color_scheme="light")
    page.goto(base + "/")
    page.wait_for_selector(".row")
    page.wait_for_timeout(800)
    with tempfile.TemporaryDirectory() as tmp:
        frames: list[tuple[Path, float]] = []

        def film(seconds: float, until: str = "") -> None:
            end = time.monotonic() + seconds
            while time.monotonic() < end or (until and not page.query_selector(until)):
                if time.monotonic() > end + 30:
                    sys.exit(f"demo.gif: {until} never appeared")
                shot = Path(tmp) / f"{len(frames):04d}.png"
                taken = time.monotonic()
                page.screenshot(path=str(shot))
                frames.append((shot, taken))

        film(1.5)
        chat.append_held(path, ANSWER_RECORDS)
        # Rows are keyed `<harness>:<id>`.
        film(2.2, f'#sections [data-section="waiting"] .row[data-id="codex:{chat.id}"]')
        row = page.locator(f'.row[data-id="codex:{chat.id}"]')
        row.hover()
        film(0.6)
        row.click()
        film(1.4, "#open-codex")
        page.hover("#open-codex")
        film(2.5)
        page.close()
        # Each frame lasts until the next one was taken, so the GIF keeps real time.
        script = Path(tmp) / "frames.txt"
        lines = [f"file '{shot}'\nduration {following[1] - taken:.3f}\n"
                 for (shot, taken), following in zip(frames, frames[1:])]
        script.write_text("".join(lines) + f"file '{frames[-1][0]}'\nduration 2\nfile '{frames[-1][0]}'\n")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(script), "-vf",
                        "fps=12,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];"
                        "[b][p]paletteuse=dither=bayer:bayer_scale=5", str(OUT / "demo.gif")], check=True)
    print("wrote docs/images/demo.gif")


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def wait_for(url: str, server: subprocess.Popen) -> None:
    for _ in range(40):
        if server.poll() is not None:
            sys.exit("Your Turn server exited before it was ready")
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except OSError:
            time.sleep(0.25)
    sys.exit(f"Server did not start on {url}")


def write_demo_homes(root: Path, chats: list[Chat], held: int = 0) -> tuple[dict[str, Path], list[Path]]:
    """Write made-up Codex, Claude Code and Cursor homes under `root`; the first Codex chat holds back `held` records."""
    homes = {name: root / name for name in ("codex", "claude", "cursor", "cursor-user")}
    paths = [chat.write(homes["codex"], held if index == 0 else 0) for index, chat in enumerate(chats)]
    (homes["codex"] / "session_index.jsonl").write_text(
        "".join(json.dumps({"id": c.id, "thread_name": c.title}) + "\n" for c in chats), encoding="utf-8")
    claude, cursor = demo_other_chats()
    for chat in claude:
        chat.write(homes["claude"])
    storage = homes["cursor-user"] / "globalStorage"
    storage.mkdir(parents=True)
    with sqlite3.connect(storage / "state.vscdb") as database:
        database.execute("CREATE TABLE composerHeaders (composerId TEXT UNIQUE, workspaceId TEXT, createdAt INTEGER,"
                         " lastUpdatedAt INTEGER, isArchived INTEGER, isSubagent INTEGER, value TEXT)")
        for chat, minutes_ago in cursor:
            chat.write(homes["cursor"], database, minutes_ago)
    database.close()
    return homes, paths


@contextmanager
def demo_server(chats: list[Chat], held: int = 0):
    """Serve made-up homes for all three apps; never the real ones. The first chat holds back `held` records."""
    with tempfile.TemporaryDirectory() as tmp:
        homes, paths = write_demo_homes(Path(tmp), chats, held)
        port = free_port()
        server = subprocess.Popen([str(ROOT / ".venv" / "bin" / "yourturn"), "serve", "--port", str(port),
                                   "--codex-home", str(homes["codex"]), "--claude-home", str(homes["claude"]),
                                   "--cursor-home", str(homes["cursor"]), "--cursor-user-dir", str(homes["cursor-user"])])
        try:
            base = f"http://127.0.0.1:{port}"
            wait_for(base + "/", server)
            yield base, paths[0]
        finally:
            server.terminate()
            server.wait()


def main() -> None:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        chats = demo_chats()
        with demo_server(chats) as (base, _):
            # Reduced motion so no capture lands mid-transition.
            desk = browser.new_page(viewport={"width": 1487, "height": 1058}, device_scale_factor=2,
                                    color_scheme="light", reduced_motion="reduce")
            desk.goto(base + "/")
            desk.wait_for_timeout(1500)
            desk.screenshot(path=str(OUT / "desktop.png"))
            desk.close()
            print("wrote docs/images/desktop.png")

            # Your Turn forbids framing, so the in-app browser pane shows a capture of it instead.
            pane = browser.new_page(viewport={"width": 420, "height": 700}, device_scale_factor=2,
                                    color_scheme="light", reduced_motion="reduce")
            pane.goto(f"{base}/?thread={chats[0].id}")
            pane.wait_for_timeout(1200)
            shot = base64.b64encode(pane.screenshot()).decode()
            pane.close()
            window = browser.new_page(viewport={"width": 1280, "height": 800}, device_scale_factor=2)
            window.set_content(CODEX_WINDOW.replace("THREAD", chats[0].id).replace("SHOT", shot))
            window.screenshot(path=str(OUT / "in-codex.png"))
            window.close()
            print("wrote docs/images/in-codex.png")

        # The reminders chat starts as recent, unfinished work, so its question arrives during the recording.
        live = demo_chats(reminders_started=4)
        with demo_server(live, ANSWER_RECORDS) as (base, path):
            demo_gif(browser, base, live[0], path)
        browser.close()

if __name__ == "__main__":
    main()
