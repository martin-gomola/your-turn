# Configuration

Commands, flags, the handoff install, and the handoff format. What each app records is in
[harnesses.md](./harnesses.md).

## Commands

| Command | What it does |
| --- | --- |
| `your-turn serve` | Starts the inbox on `http://127.0.0.1:8787` and runs until Ctrl+C |
| `your-turn install` | Sets up the handoff for each app it finds, then exits |
| `your-turn uninstall` | Removes exactly what `install` added |

## Flags and environment

| Flag | Commands | Default | Environment |
| --- | --- | --- | --- |
| `--port` | `serve` | `8787` | `PORT` for `make up` |
| `--codex-home` | all | `~/.codex` | `CODEX_HOME` |
| `--claude-home` | all | `~/.claude` | `CLAUDE_CONFIG_DIR` |
| `--cursor-home` | all | `~/.cursor` | none |
| `--cursor-user-dir` | `serve` | `~/Library/Application Support/Cursor/User` on macOS, `~/.config/Cursor/User` on Linux, `AppData/Roaming/Cursor/User` on Windows | none |
| `--harness` | `install`, `uninstall` | every app whose folder exists | none |

`--harness` takes `codex`, `claude`, `cursor`, or `all`. The server always binds `127.0.0.1`.
`YOUR_TURN_REPO` tells a development install where your clone is when it is not at
`~/dev/your-turn`.

### History window

Set the history window in `config.toml` at the repository root, then run `make restart`:

```toml
history_days = 14
```

The inbox shows chats whose session file changed in that many days. Direct chat links still open
older chats.

### State file

`~/.your-turn/state.json` keeps which results you have seen and which reminders you dismissed, so
every browser and tab shows the same inbox. It is the only file Your Turn writes. Entries for chats
that leave the inbox are dropped; deleting the file marks recent results unread again.

## What `install` sets up

Everything goes into your own app folders, never into a project, so no repository gains a file or
a `.gitignore` entry:

| App | What `install` sets up | What `uninstall` removes |
| --- | --- | --- |
| Codex | The `your-turn` plugin from the `your-turn` marketplace, which holds the handoff skill | The plugin and its marketplace |
| Claude Code | `~/.claude/skills/your-turn/SKILL.md` and a marked `your-turn` block in `~/.claude/CLAUDE.md` | The skill folder and the block; the rest of `CLAUDE.md` stays |
| Cursor | `~/.cursor/skills/your-turn/SKILL.md` | The skill folder |

The handoff is plain text in the agent's answer, so nothing runs in the background and no app asks
for a permission. Running `install` again changes nothing. Both commands also remove the
`your-turn` MCP server that earlier versions registered. Restart the apps after installing.

| You want | Do this |
| --- | --- |
| Only the inbox, no handoff | Run only `serve`. Recaps fall back to the first paragraph of each answer and a guessed next step. |
| The handoff format without installing anything | Paste [agents-snippet.md](./agents-snippet.md) into the app's global instructions, such as `~/.codex/AGENTS.md`. |
| To develop Your Turn | Clone the repo and run `make install`. The plugin then runs from your checkout, and the server starts in the background. |

## Handoff contract

Recaps come from the agent's final answer:

| If the final answer has | Your Turn shows |
| --- | --- |
| `**Outcome:**`, `**Next step:**`, and `**Recap:**` lines | Those lines as written |
| `**Decision:** <question> -> <chosen> (over <alternatives>). <reason>` lines | One decision each, with its options; `→` works too |
| No handoff lines | The first paragraph as the outcome, and a best-guess next step: Run, Review, or Answer |

- `**Outcome:**` is one sentence: what is now true.
- `**Next step:**` is `none`, `answer: …`, `review: …`, `approve: …`, or `run: …`.
- `**Recap:**` is added from the second turn on.
- Questions go through the app's question tool (`AskUserQuestion` in Claude Code, `AskQuestion` in
  Cursor) with options, so they show under Needs you until answered.

Decisions that older chats logged through the `log_decision` tool still show. The full skill is
[plugin/skills/your-turn-handoff/SKILL.md](../plugin/skills/your-turn-handoff/SKILL.md).

## Development

| Command | Use it when |
| --- | --- |
| `make install` | First setup, or to update the plugin |
| `make up` | Start the server in the background (`PORT=...` to change from 8787) |
| `make status` | Check whether it is running |
| `make logs` | Follow the server log |
| `make restart` | Pick up code or config changes |
| `make down` | Stop the server |
| `make test` | Run the test suite |
| `make screenshots` | Regenerate the README images from demo chats (needs Google Chrome and ffmpeg) |

| Route | Returns |
| --- | --- |
| `GET /api/inbox` | Recent chats with status, outcome, next step, and check state |
| `GET /api/threads/<key>` | Snapshot of one chat. `<key>` is `codex:<id>`, `claude:<id>`, or `cursor:<id>`; a bare id means Codex |
| `GET /api/stream?thread=<key>` | Server-sent events when that chat changes; without `thread`, inbox events |

```text
src/yourturn/                 FastAPI server, session engine, and installer
src/yourturn/harness/         One adapter per app: Codex, Claude Code, Cursor
src/yourturn/static/          Dashboard HTML, CSS tokens, and JavaScript
plugin/                       Codex plugin: manifest and the your-turn-handoff skill
tests/                        Parser and API tests
scripts/                      Demo-data screenshot and GIF generator for the README
docs/images/                  README images
```
