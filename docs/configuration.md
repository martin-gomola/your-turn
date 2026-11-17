# Configuration

Commands, flags, the handoff install, and the handoff format. What each app records is in
[harnesses.md](./harnesses.md).

## Commands

| Command | What it does |
| --- | --- |
| `your-turn serve` | Starts the inbox on `http://localhost:8787` and runs until Ctrl+C |
| `your-turn start` | Starts or reuses one verified inbox in the background; does not open a browser |
| `your-turn stop` | Stops only the matching inbox owned by the background launcher |
| `your-turn status` | Checks the identity of the inbox on the selected port |
| `your-turn install` | Sets up the handoff for each app it finds. Run in a terminal, it then starts the inbox, or says so when it is already running; from a script, or with input or output redirected, it exits |
| `your-turn uninstall` | Removes what `install` added; for Codex, also disables the owned autostart hook. Leaves a running shared inbox alone |
| `your-turn doctor` | Checks, without changing anything, whether the installed handoff matches this version |
| `your-turn cursor-rule` | Prints the [Cursor User Rule](#cursor-user-rule) to paste into Cursor, without changing anything |
| `your-turn autostart enable` | Adds the optional user-level Codex session-start hook using the current installed Python |
| `your-turn autostart disable` | Removes the owned session-start hook without stopping the shared inbox |
| `your-turn autostart status` | Reports the saved hook and interpreter status; Codex trust and loading remain unverified |

## Flags and environment

| Flag | Commands | Default | Environment |
| --- | --- | --- | --- |
| `--port` | `serve`, `start`, `status`, `autostart enable` | `8787` | `PORT` for `make up` and `make status` |
| `--state-dir` | `serve`, `start`, `stop`, `autostart enable` | `~/.your-turn` | Inbox state and background-server control files; use the same directory when starting and stopping |
| `--phone` | `serve`, `start` | off | Also serves on the Tailscale, Wi-Fi or iPhone USB-hotspot address (Tailscale first), behind a token: scan the printed QR code. The token stays in `~/.your-turn/phone-token`; delete that file to lock out paired phones. In a clone: `make phone`. |
| `--codex-home` | `serve`, `start`, `install`, `uninstall`, `doctor`, `autostart` | `~/.codex` | `CODEX_HOME` |
| `--claude-home` | `serve`, `start`, `install`, `uninstall`, `doctor` | `~/.claude` | `CLAUDE_CONFIG_DIR` |
| `--cursor-home` | `serve`, `start`, `install`, `uninstall`, `doctor` | `~/.cursor` | none |
| `--cursor-user-dir` | `serve`, `start` | `~/Library/Application Support/Cursor/User` on macOS, `~/.config/Cursor/User` on Linux, `AppData/Roaming/Cursor/User` on Windows | none |
| `--harness` | `install`, `uninstall`, `doctor` | every app whose folder exists | none |

`--harness` takes `codex`, `claude`, `cursor`, or `all`. The server binds `127.0.0.1` by default;
`--phone` also exposes its token-protected phone view on the network.
`YOUR_TURN_REPO` tells a development install where your clone is when it is not at
`~/dev/your-turn`.

### History window

Set the history window in `config.toml` at the repository root, then run `make restart`:

```toml
history_days = 14
```

The inbox shows chats whose session file changed in that many days. Direct chat links still open
older chats.

### Launcher shortcuts

Launcher has two pages of eight shortcuts, arranged as two rows of four in landscape and four rows
of two in portrait. Swipe horizontally, use the page buttons, or focus the shortcut area and press
Left/Right, Home or End. Unassigned slots stay empty and cannot launch anything.

One file defines every tile: copy [launcher.toml.example](../launcher.toml.example) to
`~/.your-turn/launcher.toml` (or your selected `--state-dir`) and restart Your Turn. Without it the
launcher shows Codex, Claude Code, Cursor and Your Turn Settings; with it, the file defines all 16
slots, the first four included, and the slots it leaves out stay empty.

```toml
[[shortcut]]
slot = 5
label = "Ghostty"
app = "Ghostty"

[[shortcut]]
slot = 6
label = "Restart inbox"
command = ["make", "restart"]
cwd = "~/dev/your-turn"
icon = "tool"
```

Each `[[shortcut]]` has a `slot` (1–16), a `label` (up to 40 characters) and exactly one action:

| Key | Does |
| --- | --- |
| `app = "Name"` | Opens an installed macOS app with `open -a`; no paths, URLs or arguments |
| `command = ["arg", ...]` | Opens a new Terminal window that runs the command, in `cwd` when given (an existing folder, absolute or `~/`) |
| `settings = true` | Opens Your Turn Settings |

`icon` is optional: `app`, `codex`, `claude`, `cursor`, `command`, `inbox`, `settings`, `tool` or
`workspace`. A mistake (an unknown key, a slot used twice, a missing folder) stops the server at
start-up with the line to fix, rather than dropping a tile.

A command is a list of arguments, never a shell string. On each press the server writes
`~/.your-turn/launcher/slot-N.command`, readable and runnable only by you, with every argument
shell-quoted, and opens it in Terminal; you see its output and stop it with Ctrl+C. The browser
sends only the slot key, never an app name, command or folder.

Anyone who can open the Deck can press these tiles. That includes a phone that scanned the QR code
from `make phone`, so only add commands you are happy to start from there. Shortcuts act on the
computer hosting Your Turn; on other operating systems they are disabled, and Your Turn Settings
still works.

### State and control files

`~/.your-turn/state.json` keeps which results you have seen and which reminders you dismissed, so
every browser and tab shows the same inbox. Entries for chats that leave the inbox are dropped.
`serve --state-dir` or `start --state-dir` places this file in the selected directory instead.

Background startup also writes `server.log` for server output, private `server.json` control metadata,
and `server.lock` to serialize start and stop operations. The optional Codex hook writes startup
diagnostics to `autostart.log` in that same directory. Phone access uses `~/.your-turn/phone-token`.
Treat the control metadata and phone token as private; they are not diagnostic files to share.

Each browser also backs up this state in `localStorage`. It restores missing server marks after a
restart or lost state file, and retries local changes after a failed save. Dismiss and restore actions
carry timestamps; a newer restore wins over an older browser backup. Backups contain only chat keys,
seen times, and reminder identifiers, and are pruned to the current inbox. With storage blocked,
server sharing still works. To fully reset marks, clear both the server state file and browser site data.

## Optional Codex autostart

Autostart is an opt-in user hook on macOS and Linux. The default Codex plugin remains instruction-only:
it bundles no hook, MCP server, or Python dependency. Manual `your-turn serve` remains available on
Windows and runs in the foreground.

### Enable

Use a persistent Python environment rather than an evictable `uvx` cache:

```sh
uv tool install your-turn
your-turn autostart enable
```

This saves an owned entry in `~/.codex/hooks.json`, preserving unrelated hooks. `--codex-home` selects
another Codex profile; `--state-dir` on `enable` selects the inbox state and control directory, and
`--port` selects the port to start or reuse.
The entry captures the exact installed Python executable. It matches every `SessionStart` source,
asynchronously with a 10-second hook timeout, and starts or reuses the shared inbox.
It does not download the latest package for each chat or open a browser.

Enabling writes the hook; it does not enable Codex's hook feature, grant trust, or prove the hook
loaded. Review it in `/hooks` in the Codex CLI or **Settings → Hooks** in the desktop app, following
[Codex's hook controls](https://learn.chatgpt.com/docs/hooks). Native hook trust and loading remain
unverified by Your Turn.

If you remove or recreate the Python environment, change runtimes, or lose a `uvx` cache used to
enable it, run `your-turn autostart enable` again from the installed runtime. Installing the plugin
alone never enables this hook.

### Disable or stop

Disable future session starts with:

```sh
your-turn autostart disable
```

This removes only the owned hook. Closing a Codex chat or disabling autostart leaves the shared
inbox running for other chats. Codex handoff uninstall also disables the owned hook and leaves the
server running. To stop the matching background inbox recorded in the selected state directory:

```sh
your-turn stop
```

`start` and `status` verify the server through its `/api/health` identity. A manually started server
can be reused, but `stop` does not kill it or an unrelated process on the port. Shutdown of a managed
instance requires its matching private control record and an authenticated shutdown request over
loopback.
An existing inbox is reused with its current profile and phone settings. Stop it before changing
those settings; use Ctrl+C for a foreground instance that the launcher does not own.
For an older running version without `/api/health`, stop it manually and restart with the new version.

### Diagnostics

```sh
your-turn autostart status
your-turn status
```

Hook status checks the saved entry and interpreter path; package availability, Codex trust, and hook
loading remain unverified. Check `~/.your-turn/autostart.log` for startup errors and
`~/.your-turn/server.log` for server output. If you chose `--state-dir`, use the logs there and pass
that directory to `stop`. A custom port selected with `your-turn autostart enable --port 8788` can
be inspected with `your-turn status --port 8788`. The default is the loopback inbox on port `8787`.

For manual background use, run `your-turn start`, open `http://localhost:8787` yourself, and use
`your-turn stop` when finished. Keep `your-turn serve` for a foreground terminal session.

## What `install` sets up

Everything goes into your own app folders, never into a project, so no repository gains a file or
a `.gitignore` entry:

| App | What `install` sets up | What `uninstall` removes |
| --- | --- | --- |
| Codex | The `your-turn` plugin from the `your-turn` marketplace, which holds the handoff skill. Without the Codex CLI, the skill in `~/.agents/skills/your-turn/SKILL.md` instead, worded for any app; Cursor reads that folder too, so it then keeps no copy of its own. Once the CLI is there, `install` adds the plugin and removes that copy | The plugin and its marketplace, and the shared skill |
| Claude Code | `~/.claude/skills/your-turn/SKILL.md` and a marked `your-turn` block in `~/.claude/CLAUDE.md` | The skill file and the block; the rest of `CLAUDE.md` stays |
| Cursor | `~/.cursor/skills/your-turn/SKILL.md` and the [rule](#cursor-user-rule) in `~/.cursor/rules/your-turn.mdc` | The skill file and the rule file |

The handoff is plain text in the agent's answer, so nothing runs in the background and no app asks
for a permission. `install` rewrites its own skill files and block whenever their text differs from
this version, whatever version they name; running it again then changes nothing. A `SKILL.md` or a
`your-turn.mdc` rule that Your Turn did not write, a symlinked one, and other files in those folders
are left alone by both commands. Both
also remove the `your-turn` MCP server that earlier versions registered, and the Cursor rule plugin
in `~/.cursor/plugins/local/your-turn` that later ones saved. Restart the apps after installing.

### Cursor User Rule

A saved skill is used only when the agent picks it. To apply the handoff in every Cursor Agent chat,
`install` saves the text below as an always-applied global rule file, `~/.cursor/rules/your-turn.mdc`.
**Customize → Rules** lists it by name, `your-turn`, under **User**, and Cursor applies it from the next
new chat. If you pasted the rule as a User Rule before, delete that one so chats do not get it twice.

Cursor's documentation describes User Rules in its settings and rules in a project's `.cursor/rules`,
not this global folder. If `your-turn` is not listed after a restart, open **Customize → Rules**, add
a **User Rule**, and paste the text below (GitHub shows a copy button on the block):

````markdown
## Your Turn handoff

End every final response to the user, including questions and review pauses, with this block at the very top or the very bottom: one
group of lines with no prose between them, each on one line with a blank line between them (chat apps
join adjacent lines into one paragraph), as plain Markdown outside code blocks. Progress updates need no block.

- `**Outcome:**` one sentence under 160 characters: the precise result, recommendation or explicit
  hypothesis, including any material limitation. Use a headline; put the essential reason and concise
  verification evidence in the body, referencing artifacts instead of raw logs or file inventories.
- `**Next step:**` `none`, `answer: …`, `decide: …`, `review: …`, `approve: …` or `run: …`, one action
  under 120 characters. Complete the authorized work you can perform before handing off. Write
  exactly `**Next step:** none` when no required human action remains; advice and disclosed
  uncertainty can also use `none`. Use `answer:` for necessary missing information; `decide:` names
  at least two options awaiting a choice; `review:` names a prepared artifact and the judgment
  actually needed; `approve:` requests genuinely pending permission, respecting prior authorization;
  `run:` names a necessary command only the user can run. Uncertainty alone does not require review.
- `**Recap:**` from the second turn on: 1-2 sentences under 400 characters covering the whole chat, not
  this turn: the goal, what is settled and why, and what is open. Keep relevant earlier choices and
  their reasons; make any superseding choice explicit.
- `**Decision:** <question> -> <chosen> (over <alternatives>). <reason>` records an actual consequential
  choice made this turn, one line each. A pending choice belongs in `Next step`, not a settled Decision.

Keep labels, prefixes, `->` and the literal `(over …)` syntax in English; write prose values in the
language of your reply and use these labels only in the block. Separate alternatives with commas
inside `(over …)`. An optional suggestion goes in the body with `**Next step:** none`. End the
response after a bottom block.

Example:

```markdown
**Outcome:** The login redirect bug is fixed and covered by a test.

**Next step:** none

**Recap:** Fixing login redirects; the fix and its test are in, nothing is open.
```

While working:

- Edit files with `StrReplace`, `Write` or `ApplyPatch`, not from the shell, so Your Turn sees them.
- After your last code edit, run the check that covers it, alone or last in a chain joined with `&&`;
  keep fixing failures when possible. State remaining failures or limits in Outcome; use `run:` only
  when necessary verification requires the user's environment.
- Ask the user to choose with `AskQuestion`. The `your-turn` skill has the details.
````

To print exactly this text instead, without changing anything (on macOS, `| pbcopy` puts it on the
clipboard):

```sh
uvx your-turn@latest cursor-rule
```

Plain `your-turn cursor-rule` works when `your-turn` is on your PATH. Cursor keeps User Rules in its own settings, so `install` cannot
add one there. Whether Cursor loaded the rule file is not visible outside Cursor, so `doctor` reports
**rule loaded: unverified** even when the file is current. A project's own `.cursor/rules` folder
applies only in that project.

### Checking the install

`your-turn doctor` compares each file with the text this version would write and reports **current**,
**missing**, **content mismatch**, or **unreadable**; run `install` to fix the last three. For Claude
Code it checks the skill and only the Your Turn block of `CLAUDE.md`, and shows nothing else from that
file. For Cursor it checks the skill and the rule file. Codex keeps the plugin in
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

- `**Outcome:**` is one sentence under 160 characters: the precise result, recommendation or explicit
  hypothesis, including any material limitation.
- `**Next step:**` is `none`, `answer: …`, `decide: …`, `review: …`, `approve: …`, or `run: …`.
  `none` means no required human action remains after the agent completes the authorized work it can
  perform. Advice and disclosed uncertainty can also use `none`; review needs a prepared artifact and
  a specific judgment that actually waits on the user.
- `**Recap:**` is added from the second turn on and covers the whole chat, keeping relevant earlier
  choices and their reasons and making any superseding choice explicit.
- `**Decision:**` records a consequential choice actually made, while pending choices stay in
  `Next step: decide:`. Keep `(over …)` in English even when the prose uses another language, and
  separate alternatives with commas.
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
| `make status` | Check the server identity on `PORT` |
| `make logs` | Follow the server log |
| `make restart` | Pick up code or config changes |
| `make down` | Stop the matching background server owned by the launcher |
| `make test` | Run the test suite |
| `make screenshots` | Regenerate the README images from demo chats (needs Google Chrome and ffmpeg) |
| `make site` | Build the install page and serve it at `http://127.0.0.1:8791` (`SITE_PORT` overrides) |

| Route | Returns |
| --- | --- |
| `GET /api/health` | App, version, PID, and instance identity used by background startup and status |
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
