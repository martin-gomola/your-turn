# Configuration

Commands, flags, the handoff install, and the handoff format. What each app records is in
[harnesses.md](./harnesses.md).

## Commands

| Command | What it does |
| --- | --- |
| `your-turn serve` | Starts the inbox on `http://127.0.0.1:8787` and runs until Ctrl+C |
| `your-turn install` | Sets up the handoff for each app it finds, then exits |
| `your-turn uninstall` | Removes exactly what `install` added |
| `your-turn doctor` | Checks, without changing anything, whether the installed handoff matches this version |
| `your-turn cursor-rule` | Prints the [Cursor User Rule](#cursor-user-rule) to paste into Cursor, without changing anything |

## Flags and environment

| Flag | Commands | Default | Environment |
| --- | --- | --- | --- |
| `--port` | `serve` | `8787` | `PORT` for `make up` |
| `--codex-home` | all but `cursor-rule` | `~/.codex` | `CODEX_HOME` |
| `--claude-home` | all but `cursor-rule` | `~/.claude` | `CLAUDE_CONFIG_DIR` |
| `--cursor-home` | all but `cursor-rule` | `~/.cursor` | none |
| `--cursor-user-dir` | `serve` | `~/Library/Application Support/Cursor/User` on macOS, `~/.config/Cursor/User` on Linux, `AppData/Roaming/Cursor/User` on Windows | none |
| `--harness` | `install`, `uninstall`, `doctor` | every app whose folder exists | none |

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
| Claude Code | `~/.claude/skills/your-turn/SKILL.md` and a marked `your-turn` block in `~/.claude/CLAUDE.md` | The skill file and the block; the rest of `CLAUDE.md` stays |
| Cursor | `~/.cursor/skills/your-turn/SKILL.md`; the User Rule you add yourself from `your-turn cursor-rule` | The skill file |

The handoff is plain text in the agent's answer, so nothing runs in the background and no app asks
for a permission. `install` rewrites its own skill files and block whenever their text differs from
this version, whatever version they name; running it again then changes nothing. A `SKILL.md` that
Your Turn did not write, and other files in the skill folder, are left alone by both commands. Both
also remove the `your-turn` MCP server that earlier versions registered. Restart the apps after
installing.

### Cursor User Rule

A saved skill is used only when the agent picks it. To apply the handoff in every Cursor Agent chat,
open **Customize → Rules** in Cursor, add a **User Rule**, and paste the text below
(`your-turn cursor-rule`, or `make cursor-rule` in a checkout, prints exactly this text). Cursor keeps User Rules in its own settings, so `install` cannot add one and `doctor` reports
**activation unverified** even when the skill is current. A `.cursor/rules` folder belongs to one
project and is not a User Rule.

```markdown
## Your Turn handoff

End every response to the user, on every turn, with these lines at the very top or the very bottom, as
one group with no prose between them, each on one line, as plain Markdown outside code blocks:
`**Outcome:**` (one sentence: what is now true), `**Next step:**` (`none`, `answer: …`, `decide: …`,
`review: …`, `approve: …` or `run: …`), and from the second turn on `**Recap:**` (1-2 sentences under 400
characters: goal, what is settled, what is open). Keep the labels and prefixes in English, even when you
reply in another language, and start no other line with them. When the task is done, write exactly
`**Next step:** none` and stop; an optional suggestion goes in the body, and never close with a polite
offer such as "Let me know if…" or "Should I also…?". A question the user must react to also goes in
`Next step`. Add `**Decision:** <question> -> <chosen> (over <alternatives>). <reason>` only for a
non-trivial trade-off (architecture, edge-case behavior, library or approach), one line each. Edit files
with `StrReplace`, `Write` or `ApplyPatch`, not from the shell, so Your Turn sees them. After your last code edit, run the
check that covers it, alone or last in a chain joined with `&&`; if you cannot, make the next step
`run: <command>`. Ask the user to choose with `AskQuestion`. The `your-turn` skill has the details.
```

### Checking the install

`your-turn doctor` compares each file with the text this version would write and reports **current**,
**missing**, **content mismatch**, or **unreadable**; run `install` to fix the last three. For Claude
Code it checks the skill and only the Your Turn block of `CLAUDE.md`, and shows nothing else from that
file. Codex keeps the plugin in its own cache, so the plugin is **unverified**. Neither `doctor` nor
the saved files prove that an app has loaded the handoff into a chat.

| You want | Do this |
| --- | --- |
| Only the inbox, no handoff | Run only `serve`. Recaps fall back to the first paragraph of each answer and a guessed next step. |
| The handoff format without installing anything | Paste [agents-snippet.md](./agents-snippet.md) into the app's global instructions, such as `~/.codex/AGENTS.md`. |
| To develop Your Turn | Clone the repo and run `make install`. It runs `your-turn install` for each app it finds, with the Codex plugin from your checkout when the Codex CLI is installed, and starts the server in the background. |

## Handoff contract

Recaps come from the agent's final answer:

| If the final answer has | Your Turn shows |
| --- | --- |
| `**Outcome:**`, `**Next step:**`, and `**Recap:**` lines | Those lines as written |
| `**Decision:** <question> -> <chosen> (over <alternatives>). <reason>` lines | One decision each, with its options; `→` works too |
| `**Outcome:**` without `**Next step:**` | The outcome, marked **No next step** |
| No handoff lines | The first paragraph as the outcome, and a best-guess next step (Run, Review, or Answer) marked **Inferred**; with none found, **No handoff** |

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
| `make install` | First setup, or to update the handoff |
| `make doctor` | Check, without changing anything, whether the installed handoff is current |
| `make cursor-rule` | Print the Cursor User Rule to paste into Customize → Rules |
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
