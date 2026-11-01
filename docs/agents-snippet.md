# Handoff format without automatic setup

Your Turn supports Codex, Claude Code, and Cursor. `your-turn install` adds the handoff instructions
to each app in its native way. If you want to set them up yourself, paste the block below into an
instruction file that your agent reads, such as `~/.codex/AGENTS.md` for Codex or a repository's
applicable instruction file.

The handoff is plain text; Your Turn reads it from the agent's final answer to build recaps and find
next steps.

```markdown
## Your Turn handoff

I run many agent chats at once, across apps, and triage them in the Your Turn inbox. End every response
to me, on every turn, with these lines at the very bottom, each on one line, as plain Markdown outside
code blocks:

**Outcome:** <one sentence: what is now true, or what you found>
**Next step:** <none | answer: <question> | decide: <options> | review: <what to look at> | approve: <plan> | run: <command>>
**Recap:** <from the second turn on, 1-2 sentences under 400 characters: the chat's goal, what is settled, what is open>
**Decision:** <question> -> <chosen> (over <alternatives>). <reason>

Any step other than `none` puts the chat under Needs you; start it with one of the prefixes above.
When the task is done, write `Next step: none` and stop; never close with a polite offer such as
"Let me know if…" or "Should I also…?". Write a Decision line only for a non-trivial trade-off
(architecture, edge-case behavior, library or approach), one line each with `->`, not for routine edits.

Keep the details above the handoff short. Do not repeat the outcome or list changed files and test
results. Run the checks that cover your last code edit (documentation-only edits need none); if one
fails, say so in the outcome, and if you cannot run it, make the next step `run: <command>`.
```
