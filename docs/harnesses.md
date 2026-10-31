# Harnesses

How Your Turn reads Codex, Claude Code, and Cursor, and what each one can and cannot show.
Flags and the handoff format are in [configuration.md](./configuration.md).

## What Your Turn reads

Each app already writes its chats to disk. Your Turn follows those files as they change and turns
each chat into a short recap. It never writes to them.

| App | What Your Turn reads | Change the location with |
| --- | --- | --- |
| Codex | Session files under `~/.codex/sessions`, and chat titles from `~/.codex/session_index.jsonl` | `--codex-home` or `CODEX_HOME` |
| Claude Code | Transcripts under `~/.claude/projects` | `--claude-home` or `CLAUDE_CONFIG_DIR` |
| Cursor | Agent transcripts under `~/.cursor/projects/*/agent-transcripts`, where Cursor writes them | `--cursor-home` |
| Cursor | Chat titles, folders, branches, last edits, archived and sub-agent flags, and pending approvals from `globalStorage/state.vscdb`, opened with SQLite `mode=ro` | `--cursor-user-dir` (default: `~/Library/Application Support/Cursor/User` on macOS, `~/.config/Cursor/User` on Linux, `AppData/Roaming/Cursor/User` on Windows) |

Newer Cursor versions write no transcript for top-level chats and keep their messages in the cloud.
Those chats come from their `state.vscdb` row alone: title, folder, branch, the files Cursor lists as
edited, pending approval, and last update.

## What each app records

The apps do not record the same things, so each chat shows only what its source can back up:

| | Codex | Claude Code | Cursor |
| --- | --- | --- | --- |
| Turn start and end | Logged by Codex | Inferred from prompts and the last text block | Logged in the transcript; without one, only the last update |
| Questions to you | Structured questions with options | `AskUserQuestion`, caught mid-turn while the agent waits | `AskQuestion`; the answer text is not recorded |
| Pending approvals | Not logged | Not logged; a quiet chat names the tool call still without a result | `hasBlockingPendingActions` from `state.vscdb` |
| Check results | Real exit codes | Pass or fail (tool error flag) | Not recorded |
| Timestamps | Per event | Per event | Per turn |
| Token usage | Yes | Yes | No |
| Handoff from `install` | Plugin with the skill | Skill and `CLAUDE.md` block | Skill |
| Chat action | **Open in Codex** | **Copy resume command** (`claude --resume <id>`) | **Open in Cursor** (project folder) |

## Needs you

A chat lands in **Needs you** when it has:

- an unanswered question,
- a pending Cursor approval (ignored after 24 hours without activity), or
- a finished turn whose next step is Answer, Review, Approve, Run, Decide, or Do.

A working chat silent for two minutes gets the **Quiet** tag. It may be waiting on an approval or a
long command, so Quiet never counts as Needs you. For Claude Code, its tooltip names the call still
waiting, such as `Bash: make deploy`.

**Dismiss reminder** clears a chat from Needs you in this browser. It never answers anything in the
agent's app.

## Check tags

A check is a command that runs a test, lint, type-check, or build tool (`pytest`, `ruff`, `tsc`,
`npm test`, `make check`, and similar); `rg pytest` is a search, not a check. A later run of the
same check replaces the earlier result.

| Tag | When |
| --- | --- |
| **Check failed** | The latest check failed |
| **Edits unchecked** | Code changed with no test or lint after it |

Edits to Markdown, text, and `docs/` alone raise neither tag, so a README fix raises no alarm.

## What stays out

The inbox lists only chats you opened and only what you typed:

- Sub-agents: Codex sub-agent threads and headless `codex exec` runs, Claude Code sidechain
  transcripts, and Cursor composers flagged as sub-agents. Starting one shows as a step in its
  parent chat.
- Archived Cursor chats, empty Cursor transcripts, transcripts Cursor no longer indexes in
  `state.vscdb` (deleted or cleaned-up chats), and Cursor rows with no title or update time (drafts),
  plus every chat with no activity within `history_days`.
- Abandoned Cursor turns: a turn with no end, no pending approval or question, and no transcript
  write for an hour is shown as stopped instead of Working.
- Context the apps inject into prompts: Codex environment blocks, Claude Code system reminders,
  hook output and slash-command wrappers, and Cursor's context tags.
- Unreadable data: malformed lines are skipped, a file that shrinks is re-read from the start, and
  an unreadable `state.vscdb` drops Cursor titles, approvals, and the archived and sub-agent
  filters, while the transcripts still load.

## Limits

| App | Limit | What you see |
| --- | --- | --- |
| All | Recaps come from the agent's final answer | Without handoff lines: the first paragraph and a guessed next step |
| Codex, Claude Code | Approval requests are not logged | Working, then Quiet. Quiet never counts as Needs you; a long command looks the same |
| Claude Code | The tool call waiting on approval is known | Quiet names it, such as `Bash: make deploy` |
| Claude Code | No exit codes, only error or not | Checks show pass or fail without the code |
| Claude Code | No chat deep link | **Copy resume command** |
| Cursor | Approvals are logged | Needs you with **Approve pending action in Cursor**; ignored after 24 hours without activity |
| Cursor | Transcripts record commands, not results | No pass or fail; timeline times per turn |
| Cursor | Chats without a transcript | Title, folder, branch and edited files only; Working only if updated in the last two minutes |
| Cursor | No global instructions file | The skill applies when the agent picks it, not in every chat |
| Cursor | No chat deep link | **Open in Cursor** opens the project folder |
