"""Serve made-up chats in every Deck state for design QA: `make demo`, then open http://127.0.0.1:8790/deck.

Uses disposable Codex, Claude Code and Cursor homes and inbox state (demo/server.py), so no real chat or
preference is read or written. Each chat exists to show one state; the card it lands on:

| Chat                                   | Phase code | What it exercises                                              |
|----------------------------------------|------------|----------------------------------------------------------------|
| Migrate invoices to the new ledger     | ACK        | question with options, 82% context (amber zone), 14 files, decision, tools, laps |
| Ship the ledger migration              | ACK        | `approve` step: the primary action reads "Approve in …"        |
| Fix the flaky checkout test            | FAIL       | latest check failed: red frame and code                       |
| Fix recipe import (Claude Code)        | ACK        | Claude question                                                |
| Upgrade Vite to v6 (Cursor)            | ACK        | Cursor approval; no laps or token usage (CTX unknown)          |
| Speed up the nightly export job        | RUN        | fourth lap at 92% context (red zone), runway under one turn, live tool, Δ delta |
| Reindex the invoice search             | IDLE       | working but silent for half an hour (quiet)                    |
| Add hourly forecast chart (Claude Code)| RUN → IDLE | turns quiet about two minutes after start-up                   |
| Rename every legacy billing setting …  | DONE       | long title; a slow last lap (Δ in amber or red)               |
| Bump all dependencies                  | DONE       | turn stopped by the user                                       |
| Add a CSV export button                | DONE       | finished two days ago (Earlier)                                |
| README chats (demo/chats.py)           | DONE       | a decision, a reply round-trip, a docs-only change            |

Plan usage: Codex 38% / 77% and Claude 18% / 92% (red) in the 5-hour and weekly cards.
Times are relative to start-up; restart to reset the quiet and live states.
"""

from __future__ import annotations

import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from demo.chats import demo_chats  # noqa: E402
from demo.fixtures import Chat  # noqa: E402
from demo.server import serve_demo, write_demo_homes  # noqa: E402
from yourturn import usage as plan_usage  # noqa: E402

PORT = 8790
NOW = time.time()
RESET_5H, RESET_7D = int(NOW + 2 * 3600 + 40 * 60), int(NOW + 2 * 86400 + 17 * 3600)
# Claude Code's plan usage as the opt-in status line capture saves it (see yourturn/usage.py).
CLAUDE_USAGE = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(NOW)), "rate_limits": {
    "five_hour": {"used_percentage": 18, "resets_at": int(NOW + 3 * 3600)},
    "seven_day": {"used_percentage": 92, "resets_at": int(NOW + 86400 + 5 * 3600)}}}


def usage(chat: Chat, context: int, window: int, total: int, cached: float) -> Chat:
    """Report token usage: `context` tokens in the window and a session total with a cached share."""
    chat._add("event_msg", {"type": "token_count", "info": {
        "total_token_usage": {"input_tokens": total, "cached_input_tokens": int(total * cached),
                              "output_tokens": total // 40, "total_tokens": total + total // 40},
        "last_token_usage": {"input_tokens": context, "output_tokens": 1_200, "total_tokens": context + 1_200},
        "model_context_window": window},
        # Codex's account quota, as its transcripts record it: 5-hour and weekly windows.
        "rate_limits": {"primary": {"used_percent": 38, "window_minutes": 300, "resets_at": RESET_5H},
                        "secondary": {"used_percent": 77, "window_minutes": 10_080, "resets_at": RESET_7D}}})
    return chat


def tool(chat: Chat, server: str, name: str, times: int = 1) -> Chat:
    for _ in range(times):
        chat._item({"type": "McpToolCall", "server": server, "tool": name, "status": "completed", "arguments": {}})
    return chat


def lap(chat: Chat, prompt: str, files: list[str], context: int) -> Chat:
    """One finished turn: think, edit, run a check, answer, report usage, complete."""
    chat.ask(prompt).think("**Reading the code**").edit(*files).run("uv run pytest -q")
    chat._item({"type": "AgentMessage", "phase": "final_answer",
                "content": [{"type": "Text", "text": "**Outcome:** Done.\n\n**Next step:** none."}]})
    usage(chat, context, 400_000, context * 6, 0.93)
    chat._add("event_msg", {"type": "task_complete", "turn_id": f"t{chat.turn}"})
    return chat


def needs_you() -> list[Chat]:
    files = [f"src/billing/{name}.py" for name in ("invoice", "ledger", "tax", "currency", "export", "refunds")]
    files += [f"tests/billing/test_{name}.py" for name in ("invoice", "ledger", "tax", "currency", "export")]
    files += ["docs/BILLING.md", "migrations/0042_invoice_totals.sql", "frontend/src/features/billing/InvoiceTable.tsx"]
    blocked = Chat(11, "Migrate invoices to the new ledger", "billing", 40)  # ~50 records end ~15 min ago, inside the 60-min token trace
    # Earlier laps give the Needs you card its full trace band (laps, context per lap, tokens).
    for turn, context in enumerate((90_000, 170_000, 250_000), 1):
        lap(blocked, f"Ledger step {turn}.", [f"src/billing/ledger_step_{turn}.py"], context)
    (blocked.ask("Move invoice totals onto the new ledger tables.")
               .think("**Mapping invoice rows onto ledger entries**")
               .decide("Backfill totals now or lazily?", ["Backfill now", "Lazily on read"], "Backfill now", "One migration, simpler reads"))
    tool(tool(blocked, "context7", "query-docs", 6), "code-review-graph", "query_graph", 9)
    # A failing run fixed by a rerun of the same check: the latest result passes, so the card stays ACK.
    blocked.edit(*files).run("uv run pytest -q", 1).edit("src/billing/ledger.py").run("uv run pytest -q")
    blocked.answer("**Outcome:** Invoice totals read from the ledger; 212 tests pass.\n\n"
                   "**Next step:** answer: choose how to handle invoices with mixed currencies.",
                   {"title": "Convert mixed-currency invoices at the invoice date or keep them in their own currency?",
                    "options": ["Convert at invoice date", "Keep original currency"]})
    usage(blocked, 328_000, 400_000, 4_100_000, 0.96)  # after answer(), which reports its own usage

    approve = (Chat(15, "Ship the ledger migration", "billing", 12)
               .ask("Get the ledger migration ready to merge.")
               .edit("migrations/0043_ledger_flag.sql", "src/billing/flags.py").run("uv run pytest -q")
               .answer("**Outcome:** The migration is ready behind a flag; 212 tests pass.\n\n"
                       "**Next step:** approve: merge the migration PR before tonight's export runs."))

    failed = (Chat(17, "Fix the flaky checkout test", "shop", 25)
              .ask("checkout.spec fails about one run in five. Fix it.")
              .think("**Looking for a race in the payment mock**")
              .edit("frontend/tests/checkout.spec.ts").run("npm test -- checkout.spec", 1)
              .answer("**Outcome:** The retry fix did not hold; checkout.spec still fails about one run in five.\n\n"
                      "**Next step:** run: npm test -- checkout.spec --repeat 20 to capture a failing trace."))
    return [blocked, approve, failed]


def working() -> list[Chat]:
    running = Chat(12, "Speed up the nightly export job", "billing", 18)  # ~35 records, 30s apart, end near now
    for turn, context in enumerate((96_000, 214_000, 301_000), 1):
        lap(running, f"Export step {turn}: make it faster.", [f"src/export/stage_{turn}.py"], context)
    running.ask("Now parallelise the upload stage.").think("**Profiling the upload stage**")
    tool(running, "code-review-graph", "query_graph", 4).edit("src/export/upload.py", "src/export/pool.py")
    running.run("uv run pytest -q tests/export")
    usage(running, 368_000, 400_000, 2_300_000, 0.91)
    tool(running, "context7", "query-docs")

    # Still "working", but its last record is about half an hour old: the Deck shows it as IDLE (quiet).
    idle = Chat(16, "Reindex the invoice search", "billing", 45)
    lap(idle, "Reindex step 1.", ["src/search/index.py"], 60_000)
    idle.ask("Rebuild the search index for archived invoices.").think("**Batching the archived rows**")
    idle.run("uv run python -m billing.reindex --archived")
    return [running, idle]


def ready() -> list[Chat]:
    # Two quick laps, then a long last one, so the finished card shows a slower-than-usual Δ.
    renamed = Chat(13, "Rename every legacy billing setting to the new configuration schema and update the docs", "billing", 40)
    lap(renamed, "Rename the invoice settings.", ["src/billing/settings.py"], 40_000)
    lap(renamed, "Rename the tax settings.", ["src/billing/tax_settings.py"], 70_000)
    renamed.ask("Rename the remaining legacy settings and update the docs.").think("**Listing every legacy key**")
    tool(renamed, "code-review-graph", "query_graph", 6).edit("src/billing/settings.py", "docs/CONFIG.md")
    tool(renamed, "context7", "query-docs", 4).run("uv run pytest -q")
    renamed.answer("**Outcome:** All 14 legacy settings use the new names; old names still load with a warning.\n\n"
                   "**Next step:** none.")

    stopped = Chat(18, "Bump all dependencies", "shop", 60).ask("Bump every dependency to its latest minor.")
    stopped.edit("package.json", "package-lock.json")
    stopped._add("event_msg", {"type": "turn_aborted", "turn_id": f"t{stopped.turn}", "reason": "interrupted"})

    earlier = (Chat(14, "Add a CSV export button", "billing", 2_880)
               .ask("Add a CSV export to the invoice list.")
               .edit("frontend/src/features/billing/ExportButton.tsx").run("npm test")
               .answer("**Outcome:** The invoice list has a CSV export.\n\n**Next step:** none."))
    return [renamed, stopped, earlier]


def qa_chats() -> list[Chat]:
    return [*needs_you(), *working(), *ready(), *demo_chats()[1:]]


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    with tempfile.TemporaryDirectory() as tmp:
        write_demo_homes(Path(tmp), qa_chats())
        # The demo's own Claude capture, so the real one in ~/.your-turn is never read.
        plan_usage.CAPTURE_PATH = Path(tmp) / "claude-usage.json"
        plan_usage.CAPTURE_PATH.write_text(json.dumps(CLAUDE_USAGE), encoding="utf-8")
        print(f"Deck QA demo: http://127.0.0.1:{port}/deck (made-up chats; Ctrl-C to stop)", flush=True)
        serve_demo(Path(tmp), port)


if __name__ == "__main__":
    main()
