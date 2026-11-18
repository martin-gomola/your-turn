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


def sync(source: Path, root: Path = ROOT) -> None:
    commit = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    contents = {}
    for name in FILES:
        relative = f"{SOURCE}/{name}"
        data = subprocess.check_output(["git", "-C", str(source), "show", f"{commit}:{relative}"])
        if (source / relative).read_bytes() != data:
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
    parser.add_argument("--source", type=Path, help="local your-turn-loop checkout with committed changes")
    parser.add_argument("--check", action="store_true", help="verify the packaged snapshot without Git or network access")
    args = parser.parse_args()
    if args.source:
        sync(args.source.resolve())
    else:
        check()
    print("Pinned handoff snapshot verified.")
