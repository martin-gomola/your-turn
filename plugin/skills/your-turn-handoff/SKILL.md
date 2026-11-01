---
name: your-turn-handoff
description: End every response to the user with the Your Turn handoff (Outcome and Next step lines, plus Recap on multi-turn chats and Decision for real trade-offs), and run checks after your last code edit. Always active for every task and every turn in Codex so the user can triage chats across apps at a glance.
metadata:
  version: "0.2.1"
---

# Your Turn handoff

The user triages many parallel agent chats across apps in the Your Turn inbox, which parses the end of your final message on every turn.

End **every** response to the user (including turns that ask a question or pause for review) with this block at the very bottom, each field on its own single line, as plain Markdown (not inside backticks or a code block). `Outcome` is required: without it Your Turn ignores the whole block. Write nothing after the block, and no line in the body may start with `Next:`, `Result:` or `Outcome:`.

    **Outcome:** <one sentence: what is now true, or what you found>
    **Next step:** <none | answer: … | decide: … | review: … | approve: … | run: …>
    **Recap:** <1-2 sentences, <400 chars: goal, what is settled, what remains open>
    **Decision:** <question> -> <chosen> (over <alternatives>). <reason>

Include `Recap` on every turn after the first, and `Decision` only when a non-trivial trade-off was made this turn.

## `Next step` taxonomy (Poka-yoke)

Any value other than `none` places the chat into **Needs you**. Start it with one of these prefixes; text without a prefix still lands there as a generic "To do", so always pick the closest prefix:

- `none` — task is complete and verified; nothing waits on the user. Write exactly `none`, not "no further action".
- `answer: <question>` — blocked on missing requirements, reproduction steps, or ambiguous specs.
- `decide: <options>` — blocked on an architectural or product choice between valid options.
- `review: <artifact>` — code or analysis is ready; the user should inspect a diff, file, or report.
- `approve: <action>` — waiting for permission before a destructive, external, or high-blast-radius action (e.g. git push, schema drop).
- `run: <command>` — the user must execute a command you cannot run in this environment.

Stop generating immediately after the handoff block. When `Next step` is `none`, do not add trailing polite questions ("Let me know if...", "Should I also...?").

## High-signal `Decision` & `Recap`

- **Decisions:** Log only trade-offs a human reviewer needs to know (architecture, edge-case policy, library choice). Skip routine edits. Keep each on one line with `->` between question and choice (without it the line is dropped), one line per independent trade-off. Separate alternatives in `(over …)` with commas and omit it if none is worth naming.
- **Recap as state, not history:** On one line, compress the whole session into current state (Goal + Settled + Open) so the user (and you, after context compaction) can resume with zero scrolling.
- **No duplication:** Keep the body above the handoff brief. Do not list changed files or raw test outputs—Your Turn extracts those directly from the session logs.

## Verification before handoff

Your Turn automatically flags **Edits unchecked** if you modify code without running a check afterwards, and **Check failed** if the last check failed. After your final code edit, run the test, lint, type check, or build that covers it (for example `pytest`, `ruff`, `mypy`, `npm test`, `node --test`, `tsc`, `cargo test`, `go test`, `swift test`, `make check`). Documentation-only edits (`.md`, `.rst`, `.txt`, `docs/`) need no check. If a check still fails, say so in `Outcome`; if you cannot run it, make the next step `run: <command>`.

## Examples

Completed one-shot task:

```
Fixed the off-by-one in the pager.

**Outcome:** The last page now shows its final row.
**Next step:** none
```

Later turn, ready for review, with a trade-off:

```
**Outcome:** The importer skips malformed rows instead of aborting the file.
**Next step:** review: the skipped-row log format in importer.py
**Recap:** Goal: make imports tolerate bad rows. Settled: skip and log. Open: the log format.
**Decision:** Skip or abort on a malformed row? -> skip and log (over abort, silent skip). One bad row should not lose a whole import.
```

Blocked on a choice:

```
**Outcome:** Both caches cut dashboard latency below 200 ms; they differ in how stale data can get.
**Next step:** decide: Redis with a 60 s TTL, or an in-process LRU per worker?
**Recap:** Goal: faster dashboard. Settled: queries are the bottleneck. Open: which cache.
```
