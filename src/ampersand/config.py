"""Centralized config.json management for Ampersand."""

from __future__ import annotations

import json
from pathlib import Path

from ampersand.state import DEFAULT_STATE_DIR

CONFIG_FILE = "config.json"

DEFAULTS: dict[str, dict] = {
    "logging": {
        "level": "INFO",
        "file": "~/.ampersand/ampersand.log",
    },
}


def _config_path(state_dir: Path = DEFAULT_STATE_DIR) -> Path:
    return state_dir / CONFIG_FILE


def load_config(state_dir: Path = DEFAULT_STATE_DIR) -> dict:
    """Load the full config dict from config.json."""
    path = _config_path(state_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(config: dict, state_dir: Path = DEFAULT_STATE_DIR) -> None:
    """Write the full config dict to config.json."""
    state_dir.mkdir(parents=True, exist_ok=True)
    path = _config_path(state_dir)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def get_section(section: str, state_dir: Path = DEFAULT_STATE_DIR) -> dict:
    """Return a config section merged with built-in defaults."""
    defaults = DEFAULTS.get(section, {})
    data = load_config(state_dir).get(section, {})
    return {**defaults, **data}


def set_value(dotted_key: str, value: str, state_dir: Path = DEFAULT_STATE_DIR) -> None:
    """Set a config value using a dotted key, e.g. 'logging.level'."""
    parts = dotted_key.split(".", 1)
    if len(parts) != 2:
        raise ValueError(f"Key must be in 'section.key' format, got: {dotted_key!r}")
    section, key = parts
    config = load_config(state_dir)
    if section not in config:
        config[section] = {}
    config[section][key] = value
    save_config(config, state_dir)


# ── Email config wrappers (moved from imap.py) ──────────────────────


def save_email_config(
    server: str,
    email_addr: str,
    password: str,
    port: int = 993,
    mailbox: str = "INBOX",
    state_dir: Path = DEFAULT_STATE_DIR,
) -> None:
    """Save IMAP connection settings."""
    config = load_config(state_dir)
    config["imap"] = {
        "server": server,
        "port": port,
        "email": email_addr,
        "password": password,
        "mailbox": mailbox,
    }
    save_config(config, state_dir)


def load_email_config(state_dir: Path = DEFAULT_STATE_DIR) -> dict | None:
    """Load IMAP connection settings."""
    config = load_config(state_dir)
    return config.get("imap") or None
