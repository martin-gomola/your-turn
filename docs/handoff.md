# Handoff skill

The handoff asks the agent to put its result and the action that needs you in predictable lines.
In this example, you asked the agent to compare import policies and wait for your choice before
implementation.

Without the handoff:

```text
I recommend skipping invalid rows and logging them so valid rows can still import.
The alternative is stopping at the first invalid row. Which policy should I implement?
```

With the handoff:

```text
**Outcome:** Skipping and logging invalid rows is recommended so valid rows can still import.

**Next step:** decide: skip and log invalid rows, or stop at the first invalid row?
```

If your input is needed, `Next step` names the answer, decision, review, approval, or command.
Otherwise, it says `none`. Longer chats keep a `Recap`, and consequential choices get a `Decision`.
See the [full handoff format](./configuration.md#handoff-contract).

## Install only the skill

Install **your-turn-handoff** from
[the your-turn-loop installer](https://martin-gomola.github.io/your-turn-loop/).
Select the skill, your coding agents, and project or global scope, then copy and
run the generated command. Installation uses the Skills CLI and requires Node.js
22.20+ and Git; no inbox, `uv` or Python is needed. Generated commands disable
Skills CLI telemetry for that run.

Start a new agent chat and ask:

```text
Use your-turn-handoff for the final answers in this chat.
```

The skill is maintained in
[your-turn-loop](https://github.com/martin-gomola/your-turn-loop/tree/main/skills/your-turn-handoff).
Follow its [update and removal instructions](https://github.com/martin-gomola/your-turn-loop/blob/main/docs/install.md)
to manage that installation. Agent behavior determines when the skill loads.

If you later want the inbox, run `uvx your-turn@latest serve`. Keep your existing
skill installation; you do not need to run `install` again. Full setup already
includes a bundled handoff, so choose one installation route to avoid duplicates.
