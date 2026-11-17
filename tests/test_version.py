import json
import tomllib
from pathlib import Path

from yourturn import __version__


def test_release_versions_match():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    plugin = json.loads((root / "plugin/.codex-plugin/plugin.json").read_text())
    lock = tomllib.loads((root / "uv.lock").read_text())
    frontmatter = (root / "plugin/skills/your-turn-handoff/SKILL.md").read_text().split("---", 2)[1]
    skill_version = next(line.partition(":")[2].strip().strip("\"'")
                         for line in frontmatter.splitlines() if line.strip().startswith("version:"))
    versions = {
        "runtime": __version__,
        "plugin": plugin["version"],
        "skill": skill_version,
        "lock": next(package["version"] for package in lock["package"] if package["name"] == project["name"]),
    }
    assert versions == {name: project["version"] for name in versions}
