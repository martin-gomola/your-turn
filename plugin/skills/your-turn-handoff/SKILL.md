---
name: your-turn-handoff
description: End every final user-facing answer with the Your Turn handoff (Outcome and Next step, plus Recap on multi-turn chats and Decision for settled trade-offs), and check your last code edit. Always active for every task and every turn in Codex so the user can triage chats across apps at a glance.
metadata:
  version: "0.7.0"
---

# Your Turn handoff

The user triages parallel agent chats in the Your Turn inbox. Each card should explain the result and whether anything actually waits on the user.

Put this block in every final user-facing answer, including questions and pauses for review. Progress commentary needs no block. Place it at the very top or the very bottom as one group with no prose between them, each field on one line with a blank line between fields (chat apps join adjacent lines into one paragraph), as plain Markdown outside code blocks. Always include `Outcome` and `Next step`.

    **Outcome:** <one sentence under 160 characters: the result, recommendation, finding or blocker>

    **Next step:** <none | answer: … | decide: … | review: … | approve: … | run: …>

    **Recap:** <1-2 sentences, <400 chars: the chat's goal, what is settled, what remains open>

    **Decision:** <question> -> <chosen> (over <alternatives>). <reason>

Prefer the bottom. Keep labels, action prefixes, `none`, `->` and the literal `(over …)` in English; write the prose in the language of your reply. Use those field labels only inside the handoff block, so other lines cannot be mistaken for fields.

## Field quality

The inbox shows `Outcome` and `Next step` as one-line cards and cuts them at 200 characters.

- **Outcome:** name the concrete result, recommendation or finding in familiar project terms. Mark a hypothesis as tentative. Include a limit here when it changes the meaning of the result; put supporting evidence and smaller limits in the body. For example: "The deck highlights chats needing you; phone layout is unverified."
- **Next step:** one action under 120 characters, naming what the user must do and where. Explain the reason and longer commands in the body.
- **Recap:** from the second turn on, cover the whole chat: goal, settled direction and open work. Preserve earlier choices and their essential reason while they still constrain the task; update them when superseded.
- **Decision:** record a consequential choice actually made this turn, with `->` and its reason. Use `(over …)` for meaningful alternatives, separated with commas. A choice still waiting on the user belongs in `Next step`; omit `Decision` when no trade-off was settled.

## Choose the user's next step

Complete the necessary authorized work you can perform before giving a final handoff. If progress really needs the user, prepare the artifact or diagnosis first and name the single action that unblocks it. Existing authorization remains valid.

Any value other than `none` places the chat into **Needs you**. Choose by the actual human dependency:

- `none` — no required action waits on the user. This also fits delivered advice or a finding with an explicitly stated limit. Write exactly `none`.
- `answer: <question>` — required information is missing and the user must supply it.
- `decide: <options>` — a choice belongs to the user; name at least two options, with your recommendation and their consequences in the body.
- `review: <artifact and judgment>` — the workflow actually waits for the user's assessment of a prepared artifact. A finished result or uncertainty alone does not require review.
- `approve: <action>` — a necessary action needs permission the user has not already given. A yes/no request to proceed belongs here.
- `run: <command>` — a necessary command must be run by the user because you cannot execute it.

An optional suggestion belongs in the body, with `Next step: none`. Put every question requiring a user response in `Next step` as well. Keep the answer complete without a trailing polite offer such as "Should I also…?".

With the block at the bottom, stop generating right after it. Keep the body useful: explain the premise needed to understand the result, cite existing artifacts, and summarize relevant verification rather than repeating file inventories or raw logs.

## Verification before handoff

After your last code edit, run the relevant test, lint, type check or build. Finish available authorized repairs and rerun a failed check before handing off. Your Turn flags **Edits unchecked** or **Check failed** from those events. Documentation-only edits (`.md`, `.rst`, `.txt`, `docs/`) and scratch files (the project's top-level `tmp/`, system temp folders) need no check.

Run the check alone or last in a chain joined with `&&`; a later command or a pipe can hide its failure. Report any remaining failure in `Outcome`. When a necessary check is outside your reach, state the limit and select the action that actually unblocks it; use `run:` only for a command the user must execute. Verification claims must match the evidence.

Edit files with Codex's native edit tool (`apply_patch`), not from the shell (heredocs or `write_text`): Your Turn sees edits only through that tool, so a file written from the shell is missing from the chat's file list and never raises **Edits unchecked**.

## Examples

Completed one-shot task:

```
Fixed the off-by-one in the pager.

**Outcome:** The last page now shows its final row.

**Next step:** none
```

Later turn: the user chose skip-and-log and requested a log-format review before rollout. The artifact is ready:

```
**Outcome:** The importer skips malformed rows instead of aborting the file.

**Next step:** review: confirm the skipped-row log format in importer.py

**Recap:** Goal: tolerate bad rows. Settled: skip and log to keep valid rows. Open: your log-format review.

**Decision:** Skip or abort on a malformed row? -> skip and log (over abort, silent skip). One bad row should not lose a whole import.
```

The user reserved the cache choice. Both options were benchmarked; the choice remains open:

```
**Outcome:** Both caches cut dashboard latency below 200 ms; they differ in how stale data can get.

**Next step:** decide: Redis with a 60 s TTL, or an in-process LRU per worker?

**Recap:** Goal: faster dashboard. Settled: queries are the bottleneck. Open: which cache.
```
