# Agent notes

## Direction

Your Turn is the queue for a person who already runs several paid coding agents. The handoff contract (`Outcome`, `Next step`) is the product. This inbox answers four questions in order: Notice, Understand, Judge, Act. `DESIGN.md` is the design contract. The handoff contract is defined in your-turn-loop, and the Handoff contract section of `DESIGN.md` mirrors it.

- Read-only and local. No agent controls, no new runtime, no MCP.
- Vendor-neutral. An inbox that only flatters one agent is out of scope.
- A change belongs only when it shortens Notice, Understand, Judge, or Act. The inbox measure is fewer false Needs you and a faster true one. A dashboard read for its own sake is out.
- Ship only fields the transcripts record. A dollar price, or a passed check with no recorded exit code, is not one of them.
- A claim that this is faster or cheaper ships with a public comparison and an answer key: handoff against a raw chat, or delegate against pasting a diff. The comparison table in this repository's README is not that comparison.
- `plugin/skills/your-turn-handoff/` stays a generated snapshot of that handoff contract.

## Development artifacts stay out of the repository

Write anything produced while working, rather than shipped, to an ignored folder:

- `docs/design/` (ignored by `.gitignore`): design sources, generation prompts and notes,
  reference images, QA and UX reports, browser captures and check results.
- `tmp/` (ignores its own contents): throwaway scratch files and downloads.

Never create reports like `design-qa.md` or `ux-qa.md` at the repository root. Committed files
must not link to anything under `docs/design/` or `tmp/`, because those paths do not exist in
other checkouts. Images shown in `README.md` belong in `docs/images/`.

## Handoff source

`plugin/skills/your-turn-handoff/` is a generated, pinned snapshot of the canonical
skill in `your-turn-loop`. Update it with `scripts/sync-handoff.py --source <checkout>`;
do not hand-edit it. The snapshot and `handoff-source.json` must ship together so
PyPI builds and installs work without the source repository. See `docs/handoff-source.md`.
