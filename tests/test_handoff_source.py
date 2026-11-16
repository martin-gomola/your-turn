import importlib.util
import json
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
