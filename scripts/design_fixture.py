"""Serve the real app against disposable, synthetic design-review chats.

Run: uv run python scripts/design_fixture.py --port 8788 [--full]
Uses the same fixtures as README captures, including the Claude Code and Cursor demo chats;
never reads real chats.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

import uvicorn
from readme_screenshots import Chat, write_demo_homes

from yourturn.app import create_app
import yourturn.app as app_module
from yourturn.rollout import Sessions
from yourturn.config import DEFAULT_HISTORY_DAYS


class VisualSessions(Sessions):
    """Keep visual review deterministic; full fixture uses real quiet detection."""

    def inbox(self, history_days: int = DEFAULT_HISTORY_DAYS) -> list[dict]:
        return [{**entry, "quiet": False} for entry in super().inbox(history_days)]


def chats(full: bool = False, stress: bool = False) -> list[Chat]:
    entries = [
        Chat(101, "Review schema changes", "platform-api", 360)
        .ask("Review the schema.")
        .answer("**Outcome:** Codex proposed database schema updates. Please take a look and confirm the approach.\n\n"
                "**Next step:** review: Codex proposed database schema updates. Please take a look and confirm the approach."),
        Chat(102, "Choose reminder storage", "notifications", 180)
        .ask("Choose a storage approach.")
        .answer("**Outcome:** Need your input on the best storage approach for recurring reminders.\n\n"
                "**Next step:** answer: Need your input on the best storage approach for recurring reminders."),
        Chat(103, "Improve query performance", "data-platform", 0.1)
        .ask("Improve query performance.").think("Codex is running benchmarks and optimizing slow queries."),
        Chat(104, "Build mobile layout", "web-app", 0.2)
        .ask("Build the mobile layout.").think("Codex is implementing the responsive layout for mobile."),
        Chat(105, "Update dependency policy", "infra-tools", 30)
        .ask("Update the dependency policy.")
        .answer("**Outcome:** Codex finished updating 12 dependencies. All checks pass.\n\n**Next step:** none."),
        Chat(106, "Add export preview", "analytics-ui", 120)
        .ask("Add an export preview.")
        .answer("**Outcome:** Codex completed the implementation and opened a pull request.\n\n**Next step:** none."),
        Chat(107, "Research AR access", "jumpstart-3d", 3000)
        .ask("Research AR access.")
        .answer("**Outcome:** Codex explored AR options and documented findings on permissions.\n\n**Next step:** none."),
    ]
    if full:
        entries.append(Chat(108, "Validate configuration", "platform-api", 0.3).ask("Validate configuration.").think("Checking configuration."))
        for number in range(109, 113):
            entries.append(Chat(number, f"Earlier design task {number}", "web-app", 3100 + number)
                           .ask("Review earlier work.").answer("**Outcome:** Review complete.\n\n**Next step:** none."))
    if stress:
        entries.append(Chat(120, "Inspect a long running command with detailed output and a narrow workspace", "long-workspace-project-name", 0.1)
                       .ask("Inspect the command output without hiding the next action.")
                       .run("python -m example.inspect --include " + " ".join(f"very-long-input-path-{i}/configuration.json" for i in range(35))))
    assert len({chat.id for chat in entries}) == len(entries)
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8788)
    parser.add_argument("--full", action="store_true", help="Twelve chats for truthful 2/3/2/5 filter checks")
    parser.add_argument("--stress", action="store_true", help="Add a synthetic long-command chat for overflow QA")
    parser.add_argument("--pagination", action="store_true", help="Add 24 older synthetic chats for Load more QA")
    args = parser.parse_args()
    if not args.full:
        app_module.Sessions = VisualSessions
    with TemporaryDirectory(prefix="your-turn-design-") as folder:
        entries = chats(args.full, args.stress)
        if args.pagination:
            entries.extend(Chat(number, f"Completed task {number}", "demo-project", 4000 + number)
                           .ask("Review the task.").answer("**Outcome:** Review complete.\n\n**Next step:** none.")
                           for number in range(201, 225))
        homes, _ = write_demo_homes(Path(folder), entries)
        app = create_app(homes["codex"], claude_home=homes["claude"], cursor_home=homes["cursor"], cursor_user_dir=homes["cursor-user"])
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
