---
name: your-turn-handoff
description: End every response to the user with the Your Turn handoff (Outcome and Next step lines, plus Recap on multi-turn chats and Decision for real trade-offs), and run checks after your last code edit. Always active for every task and every turn in Codex so the user can triage chats across apps at a glance.
metadata:
  version: "0.6.1"
---

# Your Turn handoff

The user triages many parallel agent chats across apps in the Your Turn inbox, which parses the end of your final message on every turn.

End **every** response to the user (including turns that ask a question or pause for review) with this block, placed at the very top or the very bottom of the message as one group of lines with no prose between them, each field on its own single line with a blank line between fields (chat apps join adjacent lines into one paragraph), as plain Markdown (not inside backticks or a code block). `Outcome` is required: without it Your Turn ignores the whole block. Keep the labels and prefixes in English, even when you reply in another language. Outside the block, no line may start with `Outcome:`, `Result:`, `Next:`, `Next step:`, `Recap:` or `Decision:`.

    **Outcome:** <one sentence under 160 characters: what is now true, or what you found>

    **Next step:** <none | answer: … | decide: … | review: … | approve: … | run: …>

    **Recap:** <1-2 sentences, <400 chars: the chat's goal, what is settled, what remains open>

    **Decision:** <question> -> <chosen> (over <alternatives>). <reason>

Include `Recap` on every turn after the first, and `Decision` only when a non-trivial trade-off was made this turn.

Prefer the bottom of the response; a contiguous block at the top is also supported. Keep the labels (`Outcome:`, `Next step:`, `Recap:`, `Decision:`) and `Next step` prefixes in English even when replying in another language, but write every value in the language of your reply. Optional suggestions are not next steps: write `none`.

## Field quality

The inbox shows `Outcome` and `Next step` as one-line cards and cuts them at 200 characters; the user reads them before anything else.

- **Outcome is a headline, not a changelog.** Under 160 characters: the one fact the user needs (the state, the answer, the blocker), with concrete nouns instead of "implemented", "done" or "polished". Lists of what changed go in the body. Bad: "The deck now shows an overview row first, highlights only the chats needing you, dims history keys, shows Codex limits, and records…". Good: "The deck leads with an overview row and highlights only chats that need you; not tried on a device yet."
- **Next step is one action under 120 characters.** Name what to do and where; long paths, command lists and the reason go in the body.
- **Recap covers the whole chat, starting from its goal.** It must still make sense to someone who saw no earlier turn. A turn-local status is not a recap. Bad: "The fix is verified; changes remain uncommitted." Good: "Goal: let the Deck run on a phone over USB. Settled: --phone and the QR code work. Open: the iPhone link has no address, and nothing is committed."

## `Next step` taxonomy (Poka-yoke)

Any value other than `none` places the chat into **Needs you**. Start it with one of these prefixes; text without a prefix still lands there as a generic "To do", so always pick the closest prefix:

- `none` — task is complete and verified; nothing waits on the user. Write exactly `none`, not "no further action".
- `answer: <question>` — blocked on missing requirements, reproduction steps, or ambiguous specs.
- `decide: <options>` — blocked on an architectural or product choice between valid options.
- `review: <artifact>` — code or analysis is ready; the user should inspect a diff, file, or report.
- `approve: <action>` — waiting for permission before a destructive, external, or high-blast-radius action (e.g. git push, schema drop).
- `run: <command>` — the user must execute a command you cannot run in this environment.

Pick by what the user has to do: "reply yes to continue" or "proceed or stop?" is `approve:`; "send me the paths, answers or URL" is `answer:`; `decide:` names at least two options (a single yes/no is `approve:`); `run:` is a command the user must execute, never one that is merely optional.

An optional suggestion the user may take or leave ("You can push when ready") belongs in the body, with `Next step: none`. A question the user has to react to always goes in `Next step` as well (`answer:` or `decide:`), not only in the body.

With the block at the bottom, stop generating right after it. When `Next step` is `none`, do not add trailing polite questions ("Let me know if...", "Should I also...?").

## High-signal `Decision` & `Recap`

- **Decisions:** Log only trade-offs a human reviewer needs to know (architecture, edge-case policy, library choice). Skip routine edits. Keep each on one line with `->` between question and choice (without it the line is dropped), one line per independent trade-off. Separate alternatives in `(over …)` with commas and omit it if none is worth naming.
- **Recap as state, not history:** On one line, compress the whole session into current state (Goal + Settled + Open) so the user (and you, after context compaction) can resume with zero scrolling.
- **No duplication:** Keep the body above the handoff brief. Do not list changed files or raw test outputs—Your Turn extracts those directly from the session logs.

## Verification before handoff

Your Turn automatically flags **Edits unchecked** if you modify code without running a check afterwards, and **Check failed** if the last check failed. After your final code edit, run the test, lint, type check, or build that covers it (for example `pytest`, `ruff`, `mypy`, `npm test`, `node --test`, `tsc`, `cargo test`, `go test`, `swift test`, `make check`). Documentation-only edits (`.md`, `.rst`, `.txt`, `docs/`) and scratch files (the project's top-level `tmp/`, system temp folders) need no check. Run a check as its own command, or as the last step of a chain joined with `&&`: one followed by `;` or `||`, or piped into another command, does not prove it passed. If a check still fails, say so in `Outcome`; if you cannot run it, make the next step `run: <command>`.

Edit files with Codex's native edit tool (`apply_patch`), not from the shell (heredocs or `write_text`): Your Turn sees edits only through that tool, so a file written from the shell is missing from the chat's file list and never raises **Edits unchecked**.

## Examples

Completed one-shot task:

```
Fixed the off-by-one in the pager.

**Outcome:** The last page now shows its final row.

**Next step:** none

**Recap:** Goal: correct pagination. Settled: the final row is visible. Open: nothing.
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
