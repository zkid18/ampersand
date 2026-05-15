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
    """Load IMAP connection settings (legacy single-account shape).

    Prefer `load_email_accounts()` which returns the full list. This is kept
    for callers that still expect a single dict — it returns the first
    configured account, or None.
    """
    accounts = load_email_accounts(state_dir)
    return accounts[0] if accounts else None


def load_email_accounts(state_dir: Path = DEFAULT_STATE_DIR) -> list[dict]:
    """Return every configured IMAP account.

    Reads `imap_accounts: [...]`. Auto-promotes the legacy single-account
    `imap: {...}` block to a one-item list so old configs keep working.
    """
    config = load_config(state_dir)
    accounts = list(config.get("imap_accounts") or [])
    legacy = config.get("imap")
    if legacy and not any(a.get("email") == legacy.get("email") for a in accounts):
        legacy = dict(legacy)
        legacy.setdefault("name", legacy.get("email", "primary"))
        accounts.append(legacy)
    return accounts


def add_email_account(
    server: str,
    email_addr: str,
    password: str,
    port: int = 993,
    mailbox: str = "INBOX",
    name: str | None = None,
    state_dir: Path = DEFAULT_STATE_DIR,
) -> None:
    """Append a new IMAP account or replace an existing one with the same email.

    Migrates the legacy `imap: {...}` single-account block into
    `imap_accounts: [...]` on first call so the two shapes don't coexist.
    """
    account = {
        "name": name or email_addr,
        "server": server,
        "port": port,
        "email": email_addr,
        "password": password,
        "mailbox": mailbox,
    }
    config = load_config(state_dir)
    accounts = list(config.get("imap_accounts") or [])
    # Pull the legacy single-account block forward so we don't lose it.
    legacy = config.get("imap")
    if legacy and not any(a.get("email") == legacy.get("email") for a in accounts):
        legacy = dict(legacy)
        legacy.setdefault("name", legacy.get("email", "primary"))
        accounts.append(legacy)
    # Replace by email if it already exists.
    accounts = [a for a in accounts if a.get("email") != email_addr]
    accounts.append(account)
    config["imap_accounts"] = accounts
    config.pop("imap", None)
    save_config(config, state_dir)


def remove_email_account(email_addr: str, state_dir: Path = DEFAULT_STATE_DIR) -> bool:
    """Drop an IMAP account by email address. Returns True if removed."""
    config = load_config(state_dir)
    accounts = list(config.get("imap_accounts") or [])
    legacy = config.get("imap")
    if legacy and not any(a.get("email") == legacy.get("email") for a in accounts):
        legacy = dict(legacy)
        legacy.setdefault("name", legacy.get("email", "primary"))
        accounts.append(legacy)
    new_accounts = [a for a in accounts if a.get("email") != email_addr]
    if len(new_accounts) == len(accounts):
        return False
    config["imap_accounts"] = new_accounts
    config.pop("imap", None)
    save_config(config, state_dir)
    return True


# ── Vault backend config ────────────────────────────────────────────


def load_backend_config(state_dir: Path = DEFAULT_STATE_DIR) -> dict | None:
    """Load the `[vault.backend]` config section.

    Shape:
        {"kind": "http", "http": {"url": "...", "api_key_env": "..."}}
        {"kind": "store", "store": {"path": "/var/lib/ampersand/vault"}}

    Returns None if not configured (caller should fall back to legacy
    save_markdown / commit_file path or raise an error).
    """
    config = load_config(state_dir)
    return config.get("vault", {}).get("backend") or None


def save_backend_config(
    backend_config: dict, state_dir: Path = DEFAULT_STATE_DIR
) -> None:
    """Persist the `[vault.backend]` config section."""
    config = load_config(state_dir)
    config.setdefault("vault", {})["backend"] = backend_config
    save_config(config, state_dir)


def clear_backend_config(state_dir: Path = DEFAULT_STATE_DIR) -> None:
    """Remove the `[vault.backend]` section so capture flows fall back."""
    config = load_config(state_dir)
    if "vault" in config and "backend" in config["vault"]:
        del config["vault"]["backend"]
        if not config["vault"]:
            del config["vault"]
        save_config(config, state_dir)
