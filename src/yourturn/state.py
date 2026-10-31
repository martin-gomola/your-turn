"""Your Turn's own inbox state, shared by every browser that opens it: which results you have seen and which
reminders you dismissed. It is the only file Your Turn writes, and it lives outside every agent's folder."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

DEFAULT_PATH = Path.home() / ".your-turn" / "state.json"
MAX_VALUE = 200


class InboxState:
    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        self.path = path
        self.version = 0
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> dict[str, dict[str, str]]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        return {name: {str(k): str(v) for k, v in (data.get(name) or {}).items()} if isinstance(data, dict) else {}
                for name in ("seen", "dismissed")}

    def snapshot(self) -> dict[str, dict[str, str]]:
        with self._lock:
            return {name: dict(values) for name, values in self._data.items()}

    def update(self, seen: dict[str, str], dismissed: dict[str, str | None], keep: set[str]) -> None:
        """Merge a browser's changes; `keep` names the chats still worth remembering, so old entries drop out."""
        with self._lock:
            for key, ended_at in seen.items():
                # The latest result seen wins, so a stale tab cannot mark a newer result unread.
                self._data["seen"][key] = max(self._data["seen"].get(key, ""), ended_at[:MAX_VALUE])
            for key, attention in dismissed.items():
                if attention is None:
                    self._data["dismissed"].pop(key, None)
                else:
                    self._data["dismissed"][key] = attention[:MAX_VALUE]
            keep = keep | set(seen) | set(dismissed)
            self._data = {name: {k: v for k, v in values.items() if k in keep} for name, values in self._data.items()}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self._data, indent=1, sort_keys=True), encoding="utf-8")
            os.replace(temporary, self.path)
            self.version += 1
