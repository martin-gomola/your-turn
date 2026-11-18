# Handoff source and packaged snapshot

The maintained handoff lives in `martin-gomola/your-turn-loop` under
`skills/your-turn-handoff/`. The copy in
`plugin/skills/your-turn-handoff/` is a generated snapshot, tracked so the existing
Your Turn GitHub plugin and the PyPI package both include the files.

To refresh it from a reviewed, committed local checkout:

```bash
make update-skill
```

The default source is `../your-turn-loop`. Update that checkout first to pick up
remote changes. For a checkout elsewhere:

```bash
make update-skill HANDOFF_SOURCE=/path/to/your-turn-loop
```

Commit the generated snapshot and `handoff-source.json` together. The record pins
the canonical Git commit and file hashes. Do not hand-edit the bundled snapshot.

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
