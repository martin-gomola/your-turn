# Handoff source and packaged snapshot

The maintained handoff lives in `martin-gomola/my-agent-skills` under
`skills/your-turn-handoff/`. The copy in
`plugin/skills/your-turn-handoff/` is a generated snapshot, tracked so the existing
Your Turn GitHub plugin and the PyPI package both include the files.

To refresh it to the latest `main` of the source repository:

```bash
make update-skill
```

This fetches `origin/main` in the local checkout (`../my-agent-skills` by default)
and copies the handoff from that commit. It does not pull or touch the checkout's
working tree, so local branches and edits there are left alone. For a checkout
elsewhere, or to snapshot local commits that are not pushed yet:

```bash
make update-skill HANDOFF_SOURCE=/path/to/my-agent-skills
```

```bash
make update-skill HANDOFF_REF=HEAD
```

Review the diff, run the tests, then commit the generated snapshot and
`handoff-source.json` together. The record pins the exact source commit and file
hashes, so a release always ships the text that was reviewed here, even after
`main` moves on. Do not hand-edit the bundled snapshot.

A repository layout change does not invalidate an existing pin: its path refers
to that historical commit. The next refresh records the current canonical path.
Client-specific adapters and the parser remain owned by Your Turn; run their tests
when updating the handoff.

The release workflow checks the snapshot offline. It never needs access to the
source repository, which can remain private. Wheel and sdist contain the real
snapshot files; no Git checkout, symlink or runtime fetch is needed by package users.

```bash
python scripts/sync-handoff.py --check
uv run pytest -q
python scripts/check-handoff-package.py
```

The package check builds a wheel and sdist, rebuilds a wheel from the extracted
sdist without Git, installs both wheels in disposable environments, and exercises
the bundled installer outside the checkout. No user agent registry is modified.
