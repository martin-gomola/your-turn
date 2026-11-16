import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sync_handoff", ROOT / "scripts/sync-handoff.py")
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def test_bundled_snapshot_matches_pin_and_rejects_drift(tmp_path):
    record = json.loads((ROOT / "handoff-source.json").read_text())
    (tmp_path / "handoff-source.json").write_text(json.dumps(record))
    for name in sync.FILES:
        target = tmp_path / sync.DESTINATION / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / sync.DESTINATION / name).read_bytes())
    sync.check(tmp_path)
    (tmp_path / sync.DESTINATION / "SKILL.md").write_text("outdated snapshot")
    with pytest.raises(ValueError, match="differs from the pinned snapshot"):
        sync.check(tmp_path)


def test_refresh_from_canonical_skills_directory(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    for name in sync.FILES:
        target = source / 'skills/your-turn-handoff' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / sync.DESTINATION / name).read_bytes())
    subprocess.run(['git', 'init', '-q', str(source)], check=True)
    subprocess.run(['git', '-C', str(source), 'add', '.'], check=True)
    subprocess.run(['git', '-C', str(source), '-c', 'user.name=Test', '-c',
                    'user.email=test@example.invalid', 'commit', '-qm', 'fixture'], check=True)
    destination = tmp_path / 'package'
    sync.sync(source, destination)
    sync.check(destination)
    record = json.loads((destination / 'handoff-source.json').read_text())
    assert record['path'] == 'skills/your-turn-handoff'
    (source / sync.SOURCE / 'SKILL.md').write_text('uncommitted')
    with pytest.raises(ValueError, match='commit the canonical'):
        sync.sync(source, destination)
