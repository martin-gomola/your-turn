---
name: your-turn-handoff
description: End every final answer with the Your Turn handoff (Outcome and Next step lines, plus Decision lines for real trade-offs), and run checks after your last code edit. Use for every task in Codex, so the user sees at a glance what happened and what they need to do.
metadata:
  version: "0.2.0"
---

# Your Turn handoff

The user triages many agent chats at once, across apps, in the Your Turn inbox, which reads these lines from
your final answer. End every final answer with them, each on its own line, outside code blocks:

- `**Outcome:** <one sentence: what is now true, or what you found>`
- `**Next step:** <one form below>`
- `**Recap:** <the whole chat: goal, what is settled, what is open>`, from the second turn on
- `**Decision:** <question> -> <chosen> (over <alternatives>). <reason>`, only for real trade-offs

`Next step` forms. Anything else after `Next step:` counts as a task for the user:

- `none`: the task is done and nothing waits on the user.
- `answer: <question>`: you need information or a choice.
- `review: <what to look at>`: the user should check a diff, report, or result.
- `approve: <plan or action>`: before something risky or irreversible.
- `run: <command>`: the user must run something you cannot.

Keep the details above the handoff short. Do not repeat the outcome or list changed files and test
results; Your Turn reads those from the chat.

## No polite trailing questions

Every step other than `none` puts the chat under **Needs you**. When the task is done, write
`**Next step:** none` and stop: no "Let me know if you want me to…" or "Should I also…?". Ask only
when you really need a decision, and then as `**Next step:** answer: <question>`.

## Decisions

Add a `Decision:` line only for a non-trivial trade-off the user needs when reviewing: architecture,
edge-case behavior, or the choice of library or approach. Skip routine edits with no real
alternative. Separate alternatives with commas, and leave out `(over …)` when none is worth naming.

## Checks

Your Turn flags **Edits unchecked** when code changed with no test, lint, type check, or build
after the last edit, and **Check failed** when a check's latest run failed. After your last code
edit, run the checks that cover it. If one still fails, say so in the outcome; if you cannot run
it, make the next step `run: <command>`.

## Examples

Done:

```
Fixed the off-by-one in the pager.

**Outcome:** The last page now shows its final row.
**Next step:** none
```

Needs the user:

```
**Outcome:** The importer skips malformed rows instead of aborting the file.
**Next step:** review: the skipped-row log format in importer.py
**Decision:** Skip or abort on a malformed row? -> skip and log (over abort, silent skip). One bad row should not lose a whole import.
```
