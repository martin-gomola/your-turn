<div align="center">

# Your Turn

### Your agents are fast. You're the queue.

![Works with Codex · Claude Code · Cursor](https://img.shields.io/badge/Works%20with-Codex%20%C2%B7%20Claude%20Code%20%C2%B7%20Cursor-56645f)
![100% Local · Read-only](https://img.shields.io/badge/100%25%20Local-Read--only-2f7a6b)

[Quickstart](#quickstart) · [Keep it next to your chat](#keep-it-next-to-your-chat) ·
[Privacy](#privacy-and-design) · [Docs](#docs)

</div>

When Codex, Claude Code, and Cursor run side by side, the slow part is your attention. The chat
blocked on you sits in a window you are not looking at, and every answer is a long log.

Your Turn is not another orchestrator, IDE wrapper, or cloud dashboard. It is a **read-only,
zero-config local inbox** that reads the logs your agents already write and answers three questions
at a glance:

1. **Who is waiting on you?** Questions, pending Cursor approvals, and finished turns, ordered by
   how long they have waited.
2. **Can you trust the result without reading the log?** **Check failed** and **Edits unchecked**
   are tied to the latest code edit.
3. **What is the exact next step, and which decisions were made?** One line each, with a button
   that opens the chat in its own app.

<div align="center">

<img src="docs/images/desktop.png" width="800" alt="Your Turn inbox with a warm header scene, status tabs, and Codex, Claude Code, and Cursor chats grouped into Needs you, Working, and New results">

<sub>Made-up demo chats from <code>make screenshots</code>, not real session data.</sub>

</div>

<details>
<summary>Watch the 12s triage flow (GIF)</summary>

<img src="docs/images/demo.gif" width="800" alt="A working chat moves into Needs you when its question arrives, then opens beside the inbox with the question and an Open in Codex button">

</details>

## Keep It Next to Your Chat

<img src="docs/images/in-codex.png" width="800" alt="Codex window with a chat on the left and Your Turn in the in-app browser on the right, showing the chat waiting for an answer and its passing check">

Your Turn runs in any browser, but it works best right beside the agent you are driving. Open
`http://127.0.0.1:8787` in the Codex in-app browser, or in a Simple Browser panel in Cursor or
VS Code, and you never switch windows to see who needs you.

## Quickstart

You need Python 3.11+, [`uv`](https://docs.astral.sh/uv/), and at least one of Codex, Claude Code,
or Cursor.

**1. Install the handoff skill**, once:

```sh
uvx --from git+https://github.com/martin-gomola/your-turn your-turn install
```

It sets up the plain-text handoff (`Outcome:`, `Next step:`, `Decision:`) for each agent it finds,
only in your home folder (`~/.codex`, `~/.claude`, `~/.cursor`), and never creates a file in your
git repositories. Restart the agents so their answers carry exact recaps, checks, and decisions.
`your-turn uninstall` removes the skills and the `~/.claude/CLAUDE.md` block again at any time.

**2. Run the inbox** whenever you want it, then open [http://127.0.0.1:8787](http://127.0.0.1:8787):

```sh
uvx --from git+https://github.com/martin-gomola/your-turn your-turn serve
```

Your existing chats appear right away. Skipping step 1 works too, with guessed recaps.

## Privacy and Design

- **Local only.** The server binds `127.0.0.1`; nothing leaves your machine.
- **Strictly read-only.** It never writes to session files or Cursor's SQLite database, and never
  starts, answers, or approves anything.
- **Zero config.** No account and no setup file; it finds the chats you already have and leaves
  out sub-agents, headless runs, and abandoned chats.

Every feature has to shorten one of the three questions above; anything else stays out.

## Docs

| Guide | What is in it |
| --- | --- |
| [docs/harnesses.md](./docs/harnesses.md) | Data sources per OS, Codex vs Claude Code vs Cursor, Needs you rules, check tags, what stays out, limits |
| [docs/configuration.md](./docs/configuration.md) | CLI flags, environment, `install` / `uninstall` per app, the handoff contract, development |
| [DESIGN.md](./DESIGN.md) | Design contract and the UI's references |
| [docs/agents-snippet.md](./docs/agents-snippet.md) | The handoff format to paste without installing anything |

## Development

```sh
make install   # first setup: plugin from your checkout, server in the background
make test      # run the test suite
```

All `make` targets and API routes are in [docs/configuration.md](./docs/configuration.md#development).

## License

[MIT](./LICENSE). Third-party icons and artwork notes are in [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md).
