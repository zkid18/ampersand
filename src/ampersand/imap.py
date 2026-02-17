"""IMAP connector for fetching emails from a mailbox."""

from __future__ import annotations

import imaplib
import json
import time
from pathlib import Path
from typing import Callable

from ampersand.email_parser import parse_email_bytes
from ampersand.models import CapturedContent
from ampersand.state import DEFAULT_STATE_DIR

CONFIG_FILE = "config.json"


def _config_path(state_dir: Path = DEFAULT_STATE_DIR) -> Path:
    return state_dir / CONFIG_FILE


def save_email_config(
    server: str,
    email_addr: str,
    password: str,
    port: int = 993,
    mailbox: str = "INBOX",
    state_dir: Path = DEFAULT_STATE_DIR,
) -> None:
    """Save IMAP connection settings."""
    state_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "imap": {
            "server": server,
            "port": port,
            "email": email_addr,
            "password": password,
            "mailbox": mailbox,
        }
    }
    path = _config_path(state_dir)

    # Merge with existing config if present
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        existing.update(config)
        config = existing

    path.write_text(json.dumps(config, indent=2), encoding="utf-8")


def load_email_config(state_dir: Path = DEFAULT_STATE_DIR) -> dict | None:
    """Load IMAP connection settings."""
    path = _config_path(state_dir)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("imap")


def _connect(config: dict) -> imaplib.IMAP4_SSL:
    """Open an IMAP connection."""
    conn = imaplib.IMAP4_SSL(config["server"], config["port"])
    conn.login(config["email"], config["password"])
    conn.select(config["mailbox"])
    return conn


def fetch_unseen(config: dict) -> list[tuple[bytes, CapturedContent]]:
    """Fetch all unseen emails and parse them. Returns (uid, content) pairs."""
    conn = _connect(config)
    try:
        _, msg_ids = conn.search(None, "UNSEEN")
        if not msg_ids[0]:
            return []

        results = []
        for uid in msg_ids[0].split():
            _, data = conn.fetch(uid, "(RFC822)")
            if data and data[0] and isinstance(data[0], tuple):
                raw = data[0][1]
                content = parse_email_bytes(raw)
                results.append((uid, content))

        return results
    finally:
        conn.close()
        conn.logout()


def mark_seen(config: dict, uid: bytes) -> None:
    """Mark an email as seen by UID."""
    conn = _connect(config)
    try:
        conn.store(uid, "+FLAGS", "\\Seen")
    finally:
        conn.close()
        conn.logout()


def watch(
    config: dict,
    on_email: Callable[[CapturedContent], None],
    poll_interval: int = 30,
) -> None:
    """Watch for new emails using IMAP IDLE (with polling fallback).

    Calls on_email for each new message. Runs forever until interrupted.
    """
    while True:
        conn = _connect(config)
        try:
            # Try IMAP IDLE if supported
            if _supports_idle(conn):
                _idle_loop(conn, config, on_email)
            else:
                _poll_loop(conn, config, on_email, poll_interval)
        except (imaplib.IMAP4.error, OSError):
            # Connection lost — reconnect after a delay
            time.sleep(5)
        finally:
            try:
                conn.logout()
            except Exception:
                pass


def _supports_idle(conn: imaplib.IMAP4_SSL) -> bool:
    """Check if the server advertises IDLE capability."""
    _, caps = conn.capability()
    if caps:
        return b"IDLE" in caps[0].upper().split()
    return False


def _idle_loop(
    conn: imaplib.IMAP4_SSL,
    config: dict,
    on_email: Callable[[CapturedContent], None],
) -> None:
    """Use IMAP IDLE to wait for new emails."""
    while True:
        # Send IDLE command
        tag = conn._new_tag().decode()
        conn.send(f"{tag} IDLE\r\n".encode())
        conn.readline()  # + idling

        # Wait for server notification (up to 29 min, then re-IDLE per RFC)
        try:
            response = conn._get_line().decode(errors="replace")
        except (TimeoutError, OSError):
            response = ""

        # End IDLE
        conn.send(b"DONE\r\n")
        conn.readline()  # tag OK

        # If we got an EXISTS notification, fetch new emails
        if "EXISTS" in response:
            _process_unseen(conn, config, on_email)


def _poll_loop(
    conn: imaplib.IMAP4_SSL,
    config: dict,
    on_email: Callable[[CapturedContent], None],
    interval: int,
) -> None:
    """Poll for new emails at a regular interval."""
    while True:
        _process_unseen(conn, config, on_email)
        time.sleep(interval)
        # NOOP to keep connection alive
        conn.noop()


def _process_unseen(
    conn: imaplib.IMAP4_SSL,
    config: dict,
    on_email: Callable[[CapturedContent], None],
) -> None:
    """Fetch and process all unseen emails on an existing connection."""
    _, msg_ids = conn.search(None, "UNSEEN")
    if not msg_ids[0]:
        return

    for uid in msg_ids[0].split():
        _, data = conn.fetch(uid, "(RFC822)")
        if data and data[0] and isinstance(data[0], tuple):
            raw = data[0][1]
            content = parse_email_bytes(raw)
            on_email(content)
            # Mark as seen
            conn.store(uid, "+FLAGS", "\\Seen")
