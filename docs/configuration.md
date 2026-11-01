# Configuration

Commands, flags, the handoff install, and the handoff format. What each app records is in
[harnesses.md](./harnesses.md).

## Commands

| Command | What it does |
| --- | --- |
| `your-turn serve` | Starts the inbox on `http://localhost:8787` and runs until Ctrl+C |
| `your-turn install` | Sets up the handoff for each app it finds. Run in a terminal, it then starts the inbox, or says so when it is already running; from a script, or with input or output redirected, it exits |
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
| Codex | The `your-turn` plugin from the `your-turn` marketplace, which holds the handoff skill. Without the Codex CLI, the skill in `~/.agents/skills/your-turn/SKILL.md` instead, worded for any app; Cursor reads that folder too, so it then keeps no copy of its own. Once the CLI is there, `install` adds the plugin and removes that copy | The plugin and its marketplace, and the shared skill |
| Claude Code | `~/.claude/skills/your-turn/SKILL.md` and a marked `your-turn` block in `~/.claude/CLAUDE.md` | The skill file and the block; the rest of `CLAUDE.md` stays |
| Cursor | `~/.cursor/skills/your-turn/SKILL.md` and the [rule](#cursor-user-rule) as a local plugin in `~/.cursor/plugins/local/your-turn` | The skill file and the plugin |

The handoff is plain text in the agent's answer, so nothing runs in the background and no app asks
for a permission. `install` rewrites its own skill files and block whenever their text differs from
this version, whatever version they name; running it again then changes nothing. A `SKILL.md` or a
`your-turn` plugin that Your Turn did not write, a symlinked one, and other files in those folders
are left alone by both commands. Both
also remove the `your-turn` MCP server that earlier versions registered. Restart the apps after
installing.

### Cursor User Rule

A saved skill is used only when the agent picks it. To apply the handoff in every Cursor Agent chat,
`install` saves the text below as an always-applied rule in a
[local plugin](https://cursor.com/docs/plugins#test-plugins-locally),
`~/.cursor/plugins/local/your-turn`. Cursor loads it after a restart or **Developer: Reload Window**,
and **Customize → Rules** then lists it.

On Enterprise plans, an admin can turn local plugins off, and they are off by default there. If the
rule is not listed after a reload, open **Customize → Rules**, add a **User Rule**, and paste the
text below (GitHub shows a copy button on the block):

````markdown
## Your Turn handoff

End every response to the user, on every turn, with this block at the very top or the very bottom: one
group of lines with no prose between them, each on one line, as plain Markdown outside code blocks.

- `**Outcome:**` one sentence: what is now true.
- `**Next step:**` `none`, `answer: …`, `decide: …`, `review: …`, `approve: …` or `run: …`. When the task
  is done, write exactly `**Next step:** none` and stop. A question the user must react to goes here.
- `**Recap:**` from the second turn on: 1-2 sentences under 400 characters (goal, what is settled, what
  is open).
- `**Decision:** <question> -> <chosen> (over <alternatives>). <reason>` only for a non-trivial trade-off
  (architecture, edge-case behavior, library or approach), one line each.

Keep the labels and prefixes in English, even when you reply in another language, and start no other
line with them. An optional suggestion goes in the body; never close with a polite offer such as
"Let me know if…" or "Should I also…?".
Keep the labels (`Outcome:`, `Next step:`, `Recap:`, `Decision:`) and `Next step` prefixes in English even when replying in another language. Optional suggestions are not next steps: write `none`.

Example:

```markdown
**Outcome:** The login redirect bug is fixed and covered by a test.
**Next step:** none
**Recap:** Fixing login redirects; the fix and its test are in, nothing is open.
```

While working:

- Edit files with `StrReplace`, `Write` or `ApplyPatch`, not from the shell, so Your Turn sees them.
- After your last code edit, run the check that covers it, alone or last in a chain joined with `&&`;
  if you cannot, make the next step `run: <command>`.
- Ask the user to choose with `AskQuestion`. The `your-turn` skill has the details.
````

To print exactly this text instead, without changing anything (on macOS, `| pbcopy` puts it on the
clipboard):

```sh
uvx --from git+https://github.com/martin-gomola/your-turn your-turn cursor-rule
```

Plain `your-turn cursor-rule` works when `your-turn` is on your PATH. Cursor keeps User Rules in its own settings, so `install` cannot
add one there. Whether Cursor loaded the plugin is not visible outside Cursor, so `doctor` reports
**rule loaded: unverified** even when the plugin is current. A `.cursor/rules` folder belongs to one
project and does not apply elsewhere.

### Checking the install

`your-turn doctor` compares each file with the text this version would write and reports **current**,
**missing**, **content mismatch**, or **unreadable**; run `install` to fix the last three. For Claude
Code it checks the skill and only the Your Turn block of `CLAUDE.md`, and shows nothing else from that
file. For Cursor it checks the skill and both files of the rule plugin. Codex keeps the plugin in
its own cache, so the plugin is **unverified**. Neither `doctor` nor
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
