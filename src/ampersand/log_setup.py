"""Configure file-based logging for Ampersand."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

_initialized = False


def setup_logging() -> None:
    """Set up root-level file logging from config.

    Idempotent — subsequent calls are no-ops.
    Creates a RotatingFileHandler (5 MB x 3 backups = ~20 MB cap).
    Falls back silently if the log directory is unwritable or config is corrupt.
    """
    global _initialized
    if _initialized:
        return
    _initialized = True

    try:
        from ampersand.config import get_section

        cfg = get_section("logging")
        level_name = cfg.get("level", "INFO")
        log_file = Path(cfg.get("file", "~/.ampersand/ampersand.log")).expanduser()
    except Exception:
        level_name = "INFO"
        log_file = Path.home() / ".ampersand" / "ampersand.log"

    level = getattr(logging, level_name.upper(), logging.INFO)

    try:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_file,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
    except OSError:
        return

    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s",
                          datefmt="%Y-%m-%d %H:%M:%S")
    )

    root = logging.getLogger("ampersand")
    root.setLevel(level)
    root.addHandler(handler)
