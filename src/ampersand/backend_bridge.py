"""Bridge between the CLI's capture flows and ampersand_core's VaultBackend.

The CLI deals in `CapturedContent` (title, url, author, body markdown, tags…).
The backend's `create()` takes a body string + frontmatter dict. This module
adapts one to the other and resolves the configured backend (or returns None
for the legacy save_markdown fallback).
"""

from __future__ import annotations

from typing import Any

from ampersand_core.backend import (
    BackendError,
    VaultBackend,
    build_backend,
)
from ampersand_core.models import CapturedContent

from ampersand.config import load_backend_config


def get_backend() -> VaultBackend | None:
    """Return the configured VaultBackend, or None if no backend is set.

    None means: fall back to the legacy save_markdown + commit_file path.
    """
    cfg = load_backend_config()
    if not cfg:
        return None
    try:
        return build_backend(cfg)
    except BackendError:
        return None


def content_to_backend_args(
    content: CapturedContent, *, prepend_heading: bool = True
) -> tuple[str, dict[str, Any]]:
    """Convert a CapturedContent into (body, frontmatter) for `backend.create()`."""
    body_md = content.content_markdown
    if prepend_heading and content.title and not body_md.lstrip().startswith("#"):
        body_md = f"# {content.title}\n\n{body_md}"
    if not body_md.endswith("\n"):
        body_md += "\n"

    # Serialize captured_at to ISO string — HTTPBackend's json= path can't
    # handle a raw datetime, and the store now accepts both datetime and ISO.
    captured_iso = content.captured_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    frontmatter: dict[str, Any] = {
        "title": content.title,
        "source": content.url,
        "type": content.content_type.value,
        "captured_at": captured_iso,
        "tags": list(content.tags),
    }
    if content.author:
        frontmatter["author"] = content.author
    if content.sender_email:
        frontmatter["sender_email"] = content.sender_email
    return body_md, frontmatter
