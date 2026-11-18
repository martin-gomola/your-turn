"""Refresh the bundled snapshot from a committed source, or check it offline."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "skills/your-turn-handoff"
DESTINATION = Path("plugin/skills/your-turn-handoff")
FILES = ("SKILL.md", "LICENSE")


def check(root: Path = ROOT) -> None:
    record = json.loads((root / "handoff-source.json").read_text())
    if set(record["files"]) != set(FILES) or len(record["commit"]) != 40:
        raise ValueError("invalid handoff source record")
    for name in FILES:
        if hashlib.sha256((root / DESTINATION / name).read_bytes()).hexdigest() != record["files"][name]:
            raise ValueError(f"bundled {name} differs from the pinned snapshot; run scripts/sync-handoff.py --source <checkout>")


def sync(source: Path, root: Path = ROOT, ref: str = "HEAD") -> None:
    git = ["git", "-C", str(source)]
    remote, _, branch = ref.partition("/")
    # A remote-tracking ref (origin/main) is fetched first, so the snapshot is that branch's latest commit.
    if branch and remote in subprocess.check_output([*git, "remote"], text=True).split():
        subprocess.run([*git, "fetch", "--quiet", remote, branch], check=True)
    commit = subprocess.check_output([*git, "rev-parse", f"{ref}^{{commit}}"], text=True).strip()
    contents = {}
    for name in FILES:
        relative = f"{SOURCE}/{name}"
        data = subprocess.check_output([*git, "show", f"{commit}:{relative}"])
        # Only a HEAD sync reads the checkout itself; uncommitted edits there would not be in the pin.
        if ref == "HEAD" and (source / relative).read_bytes() != data:
            raise ValueError("commit the canonical handoff changes before synchronizing")
        contents[name] = data
    target = root / DESTINATION
    target.mkdir(parents=True, exist_ok=True)
    for name, data in contents.items():
        (target / name).write_bytes(data)
    record = {"repository": "https://github.com/martin-gomola/your-turn-loop.git", "commit": commit,
              "path": SOURCE, "files": {name: hashlib.sha256(data).hexdigest() for name, data in contents.items()}}
    (root / "handoff-source.json").write_text(json.dumps(record, indent=2) + "\n")
    check(root)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, help="local your-turn-loop checkout")
    parser.add_argument("--ref", default="origin/main",
                        help="commit to snapshot (default: origin/main, fetched first; HEAD for local commits)")
    parser.add_argument("--check", action="store_true", help="verify the packaged snapshot without Git or network access")
    args = parser.parse_args()
    if args.source:
        sync(args.source.resolve(), ref=args.ref)
    else:
        check()
    print("Pinned handoff snapshot verified.")
