"""The README chat set: a small garden-planner and weather-widget inbox used by `make screenshots`."""

from __future__ import annotations

from demo.fixtures import Chat, ClaudeChat, CursorChat


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

