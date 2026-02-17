"""Persistent state for feed subscriptions and captured items."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_STATE_DIR = Path.home() / ".ampersand"
STATE_FILE = "state.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AppState:
    """Manages feed subscriptions and capture history."""

    def __init__(self, state_dir: Path = DEFAULT_STATE_DIR) -> None:
        self._state_dir = state_dir
        self._state_file = state_dir / STATE_FILE
        self._data = self._load()

    def _load(self) -> dict[str, Any]:
        if self._state_file.exists():
            return json.loads(self._state_file.read_text(encoding="utf-8"))
        return {"feeds": {}, "captured": []}

    def _save(self) -> None:
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    # --- Feed subscriptions ---

    def add_feed(self, url: str, name: str | None = None, tags: list[str] | None = None) -> None:
        self._data["feeds"][url] = {
            "name": name or url,
            "tags": tags or [],
            "added": _now_iso(),
        }
        self._save()

    def remove_feed(self, url: str) -> bool:
        if url in self._data["feeds"]:
            del self._data["feeds"][url]
            self._save()
            return True
        return False

    def list_feeds(self) -> dict[str, dict]:
        return dict(self._data["feeds"])

    def get_feed(self, url: str) -> dict | None:
        return self._data["feeds"].get(url)

    # --- Capture tracking ---

    def is_captured(self, url: str) -> bool:
        return url in self._data["captured"]

    def mark_captured(self, url: str) -> None:
        if url not in self._data["captured"]:
            self._data["captured"].append(url)
            self._save()

    @property
    def captured_count(self) -> int:
        return len(self._data["captured"])
