"""Render README screenshots from made-up Codex, Claude Code and Cursor homes, so no real chat content is captured.

Run with `make screenshots`. Needs Google Chrome; Playwright comes from `uvx --with playwright`.
The chats and the disposable server live in demo/; this file only films them.
"""

from __future__ import annotations

import base64
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from demo.chats import demo_chats  # noqa: E402
from demo.fixtures import ANSWER_RECORDS, Chat  # noqa: E402
from demo.server import demo_server, free_port, wait_for  # noqa: E402

OUT = ROOT / "docs" / "images"


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
    page = browser.new_page(viewport={"width": 1280, "height": 800}, color_scheme="dark")
    page.add_init_script("localStorage.setItem('theme', 'dark'); localStorage.setItem('compact-header', 'true')")
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
        write_gif(frames, Path(tmp), "demo.gif")


def write_gif(frames: list[tuple[Path, float]], tmp: Path, name: str, hold: float = 2) -> None:
    """Each frame lasts until the next one was taken, so the GIF keeps real time; the last one holds for `hold`."""
    script = tmp / "frames.txt"
    lines = [f"file '{shot}'\nduration {following[1] - taken:.3f}\n"
             for (shot, taken), following in zip(frames, frames[1:])]
    script.write_text("".join(lines) + f"file '{frames[-1][0]}'\nduration {hold}\nfile '{frames[-1][0]}'\n")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(script), "-vf",
                    "fps=12,scale=960:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128[p];"
                    "[b][p]paletteuse=dither=bayer:bayer_scale=5", str(OUT / name)], check=True)
    print(f"wrote docs/images/{name}")


def deck_gif(browser) -> None:
    """Film the Deck on its running Codex chat: the spinning status icon, live timers and the recorded log."""
    port = free_port()
    # The Deck demo serves its own made-up plan usage, so no real usage capture is read.
    server = subprocess.Popen([str(ROOT / ".venv" / "bin" / "python"), "-m", "demo.deck", str(port)], cwd=ROOT,
                              stdout=subprocess.DEVNULL)
    try:
        base = f"http://127.0.0.1:{port}"
        wait_for(base + "/deck", server)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, color_scheme="dark")
        page.add_init_script("localStorage.setItem('theme', 'dark')")
        page.goto(base + "/deck")
        page.wait_for_selector('.deck-mini[data-kind="working"]')
        page.locator('.deck-mini[data-kind="working"]').first.click()
        page.wait_for_selector('.deck-card[data-kind="working"]')
        page.mouse.move(0, 0)
        page.wait_for_timeout(800)
        with tempfile.TemporaryDirectory() as tmp:
            frames: list[tuple[Path, float]] = []
            end = time.monotonic() + 4
            while time.monotonic() < end:
                shot = Path(tmp) / f"{len(frames):04d}.png"
                taken = time.monotonic()
                page.screenshot(path=str(shot))
                frames.append((shot, taken))
            page.close()
            write_gif(frames, Path(tmp), "deck.gif", hold=0.1)
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
                                    color_scheme="dark", reduced_motion="reduce")
            desk.add_init_script("localStorage.setItem('theme', 'dark'); localStorage.setItem('compact-header', 'true')")
            desk.goto(base + "/")
            desk.wait_for_timeout(1500)
            desk.screenshot(path=str(OUT / "desktop.png"))
            desk.close()
            print("wrote docs/images/desktop.png")

            # Your Turn forbids framing, so the in-app browser pane shows a capture of it instead.
            pane = browser.new_page(viewport={"width": 420, "height": 700}, device_scale_factor=2,
                                    color_scheme="dark", reduced_motion="reduce")
            pane.add_init_script("localStorage.setItem('theme', 'dark'); localStorage.setItem('compact-header', 'true')")
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
        deck_gif(browser)
        browser.close()

if __name__ == "__main__":
    main()
