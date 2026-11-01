# Agent notes

## Development artifacts stay out of the repository

Write anything produced while working, rather than shipped, to an ignored folder:

- `docs/design/` (ignored by `.gitignore`): design sources, generation prompts and notes,
  reference images, QA and UX reports, browser captures and check results.
- `tmp/` (ignores its own contents): throwaway scratch files and downloads.

Never create reports like `design-qa.md` or `ux-qa.md` at the repository root. Committed files
must not link to anything under `docs/design/` or `tmp/`, because those paths do not exist in
other checkouts. Images shown in `README.md` belong in `docs/images/`.
