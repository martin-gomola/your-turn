# Handoff format without automatic setup

Your Turn supports Codex, Claude Code, and Cursor. `your-turn install` adds the handoff instructions
to each app in its native way. If you want to set them up yourself, paste the block below into an
instruction file that your agent reads, such as `~/.codex/AGENTS.md` for Codex or a repository's
applicable instruction file.

The handoff is plain text; Your Turn reads it from the agent's final answer to build recaps and find
next steps.

```markdown
## Your Turn handoff

I run many agent chats at once, across apps, and triage them in the Your Turn inbox. End every final
response to me, including questions and review pauses, with these lines at the very top or the very bottom,
as one group with no prose between them, each on one line with a blank line between them (chat apps join
adjacent lines into one paragraph), as plain Markdown outside code blocks. Progress updates need no block.

**Outcome:** <one sentence under 160 characters: the precise result, recommendation or explicit hypothesis, including any material limitation>

**Next step:** <none | answer: <question> | decide: <options> | review: <what to look at> | approve: <plan> | run: <command>>

**Recap:** <from the second turn on, 1-2 sentences under 400 characters covering the whole chat, not this turn: the goal, what is settled and why, what is open>

**Decision:** <question> -> <chosen> (over <alternatives>). <reason>

Keep labels, prefixes, `->` and the literal `(over …)` syntax in English; write prose values in the
language of your reply and use these labels only in the block. Separate alternatives with commas
inside `(over …)`. The outcome is a headline and the next step is one action under 120 characters;
details go in the body. Any step other than `none` puts the
chat under Needs you. Complete the authorized work you can perform before handing off. Write
exactly `Next step: none` when no required human action remains; advice and disclosed uncertainty
can also use `none`. An optional suggestion goes in the body. End the response after a bottom block.

Use `answer:` for necessary missing information; `decide:` names at least two options awaiting a
choice; `review:` names a prepared artifact and the judgment actually needed; `approve:` requests
genuinely pending permission, respecting prior authorization; `run:` names a necessary command only
the user can run. Uncertainty alone does not require review. Decision records an actual consequential
choice made this turn; pending choices belong in Next step. Recap keeps relevant earlier choices and
their reasons, making any superseding choice explicit.

Use familiar task language, the essential reason and concise verification evidence. Reference
artifacts instead of repeating raw logs or file inventories. Edit files with your app's native edit
tool, not from the shell, so Your Turn sees them. Run the checks that cover your last code edit
(documentation-only edits need none), alone or last in a chain joined with `&&`; keep fixing failures
when possible. State remaining failures or limits in Outcome; use `run:` only when necessary
verification requires the user's environment.
```
