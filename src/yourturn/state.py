"""Your Turn's own inbox state, shared by every browser that opens it: which results you have seen and which
reminders you dismissed. It is the only file Your Turn writes, and it lives outside every agent's folder."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

DEFAULT_PATH = Path.home() / ".your-turn" / "state.json"
MAX_VALUE = 200


class InboxState:
    def __init__(self, path: Path = DEFAULT_PATH) -> None:
        self.path = path
        self.version = 0
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self) -> dict[str, dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        loaded = {}
        for name in ("seen", "dismissed", "dismissed_at"):
            values = data.get(name, {}) if isinstance(data, dict) else {}
            loaded[name] = {str(k): v for k, v in values.items() if (
                type(v) is int and 0 <= v <= 2**53 - 1 if name == "dismissed_at"
                else isinstance(v, str) or (name == "dismissed" and v is None)
            )} if isinstance(values, dict) else {}
        return loaded

    def snapshot(self) -> dict[str, dict]:
        with self._lock:
            return {name: dict(values) for name, values in self._data.items()}

    def update(self, seen: dict[str, str], dismissed: dict[str, str | None], keep: set[str],
               dismissed_at: dict[str, int] | None = None) -> None:
        """Merge a browser's changes; `keep` names the chats still worth remembering, so old entries drop out."""
        with self._lock:
            for key, ended_at in seen.items():
                # The latest result seen wins, so a stale tab cannot mark a newer result unread.
                self._data["seen"][key] = max(self._data["seen"].get(key, ""), ended_at[:MAX_VALUE])
            for key, attention in dismissed.items():
                previous = self._data["dismissed_at"].get(key, 0)
                stamp = (dismissed_at or {}).get(key, max(int(time.time() * 1000), previous + 1))
                # Explicit restores remain as tombstones; an older browser must not dismiss them again.
                stored = self._data["dismissed"].get(key)
                if stamp < previous or (stamp == previous and key in self._data["dismissed"] and (
                    stored is None or (attention is not None and attention <= stored)
                )):
                    continue
                self._data["dismissed"][key] = attention[:MAX_VALUE] if attention is not None else None
                self._data["dismissed_at"][key] = stamp
            keep = keep | set(seen) | set(dismissed)
            self._data = {name: {k: v for k, v in values.items() if k in keep} for name, values in self._data.items()}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self._data, indent=1, sort_keys=True), encoding="utf-8")
            os.replace(temporary, self.path)
            self.version += 1
