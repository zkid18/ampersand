"""Persistent state for feed subscriptions and captured items."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_STATE_DIR = Path.home() / ".amperstand"
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

    # --- Vault config ---

    def set_vault(self, path: str, auto_sync: bool = False) -> None:
        self._data["vault"] = {"path": path, "auto_sync": auto_sync}
        self._save()

    def get_vault(self) -> dict | None:
        return self._data.get("vault")

    def clear_vault(self) -> None:
        self._data.pop("vault", None)
        self._save()

    # --- Email sender allowlist ---

    def add_sender(self, sender: str) -> None:
        """Add an email address or @domain to the allowlist."""
        senders = self._data.setdefault("email_senders", [])
        if sender not in senders:
            senders.append(sender)
            self._save()

    def remove_sender(self, sender: str) -> bool:
        """Remove a sender from the allowlist. Returns True if found."""
        senders = self._data.get("email_senders", [])
        if sender in senders:
            senders.remove(sender)
            self._save()
            return True
        return False

    def list_senders(self) -> list[str]:
        """Return the sender allowlist."""
        return list(self._data.get("email_senders", []))

    def is_sender_allowed(self, sender: str) -> bool:
        """Check if a sender matches the allowlist (full address or @domain)."""
        senders = self._data.get("email_senders", [])
        sender_lower = sender.lower()
        for entry in senders:
            entry_lower = entry.lower()
            if entry_lower == sender_lower:
                return True
            # Domain match: entry is "@domain.com", check sender ends with it
            if entry_lower.startswith("@") and sender_lower.endswith(entry_lower):
                return True
        return False
