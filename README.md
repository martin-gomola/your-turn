<div align="center">

# Your Turn

<p align="center"><strong>Your agents are fast. You're the queue.</strong></p>

![Works with Codex · Claude Code · Cursor](https://img.shields.io/badge/Works%20with-Codex%20%C2%B7%20Claude%20Code%20%C2%B7%20Cursor-56645f)
![Local · Read-only](https://img.shields.io/badge/Local-Read--only-2f7a6b)

[Your inbox](#your-inbox) · [Quick start](#quick-start) · [Privacy](#privacy) ·
[Why install the handoff](#why-install-the-handoff) · [Docs](#docs)

</div>

When Codex, Claude Code, and Cursor run side by side, the slow part is your attention. The chat blocked on you sits in a window you are not looking at, and every answer is a long log.

## Your inbox

<div align="center">

<img src="docs/images/desktop.png?v=1" width="800" alt="Your Turn dark inbox in Focus Mode, with Codex, Claude Code, and Cursor chats grouped by status">

<sub>Made-up demo chats from <code>make screenshots</code>, not real session data.</sub>

</div>

<details>
<summary>See the inbox beside a chat</summary>

<img src="docs/images/in-codex.png?v=1" width="800" alt="Codex chat beside the Your Turn dark inbox in Focus Mode">

</details>

<details>
<summary>Watch a chat move into Needs you</summary>

<img src="docs/images/demo.gif?v=1" width="800" alt="A chat moves into Needs you when its question arrives, then opens beside the inbox">

</details>
<br>

**Your Turn** is not another orchestrator, IDE wrapper, or cloud dashboard. It is a read-only, zero-config local inbox on `localhost:8787`. It reads the JSONL logs your agents already write and the local Cursor chat database. It answers three questions at a glance:

- ⏳ **Who is waiting on you?**<br>
  Questions, pending approvals, and unreviewed results, ordered by how long they have waited.<br>
- ✅ **Can you trust the result without reading the log?**<br>
  `Check failed` and `Edits unchecked` badges tied to the latest code edit.<br>
- ➡️ **What is the exact next step?**<br>
  One line per chat, with one click to open or resume it in its app.<br>

Your Turn runs on your machine. It does not take over agent processes, run a background service, or send chat data to the cloud. It uses no cloud account or extra agent permissions.

## Quick start

You need [`uv`](https://docs.astral.sh/uv/) and Codex, Claude Code, or Cursor. `uv` downloads Python 3.11 or newer if you do not have it. Without `uv`, install it first with `brew install uv` or [uv's installer](https://docs.astral.sh/uv/getting-started/installation/).

To see which files `install` would write, run `uvx your-turn@latest doctor` first; it changes nothing. Then run:

```bash
uvx your-turn@latest install
```

`install` adds the Your Turn handoff instructions to the agent apps it finds, then starts the inbox. Restart those agent apps, then open [http://localhost:8787](http://localhost:8787).

To start the inbox later, run:

```bash
uvx your-turn@latest serve
```

The server binds to loopback only (`127.0.0.1`). To remove the handoff, run `uvx your-turn@latest uninstall`.

<details>
<summary>Check where a release comes from, or pin one</summary>

`uvx your-turn@latest` runs the newest [PyPI release](https://pypi.org/project/your-turn/), which GitHub Actions builds from a Git tag and PyPI shows with its attestation. Without `@latest`, `uv` keeps reusing the release it downloaded first. To pin a version, use `uvx your-turn@0.4.0`, or install straight from its tag with `uvx --from git+https://github.com/martin-gomola/your-turn@v0.4.0 your-turn`.

</details>

<details>
<summary>Run with Nix instead</summary>

The repository is a flake, with dependencies pinned in `flake.lock`. This starts the inbox without changing any agent app:

```bash
nix run github:martin-gomola/your-turn
```

Only `install` and `uninstall` change agent app folders. To see what `install` would touch, run `nix run github:martin-gomola/your-turn -- doctor` first. To skip it, add the handoff by hand from [docs/agents-snippet.md](./docs/agents-snippet.md), or print the Cursor rule with `nix run github:martin-gomola/your-turn -- cursor-rule`. `nix profile install github:martin-gomola/your-turn` puts `your-turn` on your `PATH`. To pin a release, use `github:martin-gomola/your-turn/v0.4.0`.

</details>

## Privacy

- **Local only.** The server binds to `127.0.0.1`. It does not send session data anywhere.
- **Read-only session access.** Your Turn reads agent logs and Cursor's local chat database. It never edits them, starts or answers chats, or approves actions.
- **Small local state file.** `~/.your-turn/state.json` stores seen results and dismissed reminders so they stay in sync across browsers. The browser keeps a local backup.
- **No account or setup file.** Your Turn finds existing chats and leaves out sub-agents, headless runs, and abandoned chats.

## Why install the handoff?

<details>
<summary>See how the handoff keeps finished chats out of Needs you</summary>

Agents often end with a polite question such as “Would you like me to update the docs?” Your Turn can read that as a question waiting on you, even when the work is done. The handoff asks the agent to end with an `Outcome` and a `Next step`, so the inbox can show a clear result.

Without the handoff:

```text
I refactored the token refresh logic and ran pytest. All 12 tests passed.
Would you like me to update the docs or commit the changes?
```

With the handoff:

```text
I refactored the token refresh logic and ran pytest. All 12 tests passed.

**Outcome:** Token refresh is refactored and all 12 tests pass.

**Next step:** none
```

If an agent needs a decision, answer, review, or approval, `Next step` names it. See the full format in [docs/configuration.md](./docs/configuration.md#your-turn-handoff).

</details>

## Docs

| Guide | What it covers |
| --- | --- |
| [docs/harnesses.md](./docs/harnesses.md) | Data sources by OS, supported apps, inbox states, checks, and limits |
| [docs/configuration.md](./docs/configuration.md) | CLI commands and flags, app setup, handoff format, and development |
| [DESIGN.md](./DESIGN.md) | UI design contract and references |
| [docs/agents-snippet.md](./docs/agents-snippet.md) | Handoff format to add to agent instructions by hand |

## Run from a clone

```bash
git clone https://github.com/martin-gomola/your-turn.git
cd your-turn
make install
```

`make install` sets up the handoff from this checkout and starts the inbox. Open [http://localhost:8787](http://localhost:8787). Later, from the same folder:

```bash
make up        # start the inbox in the background
make down      # stop it
make doctor    # check the handoff without changing it
make test      # run the test suite
```

See [docs/configuration.md](./docs/configuration.md#development) for all `make` targets and API routes.

## License

[MIT](./LICENSE). Third-party icons and artwork are listed in [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md).
