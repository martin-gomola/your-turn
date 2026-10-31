# Handoff format without the plugin

The `your-turn` plugin ships a skill that asks Codex to end every final answer with `Outcome`
and `Next step` lines, plus a `Recap` line from the second turn on. If you do not want to install
the plugin, paste the block below into an `AGENTS.md` file instead. Use `~/.codex/AGENTS.md` for
all chats, or a repo's `AGENTS.md` for chats in that repo.

The handoff is plain text, so the block below gives Your Turn everything the plugin does.

```markdown
## Your Turn handoff

I run many agent chats at once, across apps, and triage them in the Your Turn inbox. End every final answer
with these lines, each on its own line, outside code blocks:

**Outcome:** <one sentence: what is now true, or what you found>
**Next step:** <none | answer: <question> | review: <what to look at> | approve: <plan> | run: <command>>
**Recap:** <from the second turn on: the chat's goal, what is settled, what is open>
**Decision:** <question> -> <chosen> (over <alternatives>). <reason>

Any step other than `none` puts the chat under Needs you. When the task is done, write
`Next step: none` and stop; never close with a polite offer such as "Let me know if…" or
"Should I also…?". Write a Decision line only for a non-trivial trade-off (architecture, edge-case
behavior, library or approach), not for routine edits.

Keep the details above the handoff short. Do not repeat the outcome or list changed files and test
results. Run the checks that cover your last code edit; if one fails, say so in the outcome, and if
you cannot run it, make the next step `run: <command>`.
```
