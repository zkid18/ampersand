"""Git-backed vault operations for collaborative markdown storage."""

from __future__ import annotations

import subprocess
from pathlib import Path

GITIGNORE_TEMPLATE = """\
.DS_Store
.obsidian/workspace.json
.obsidian/workspace-mobile.json
.obsidian/cache/
"""


class VaultError(Exception):
    """Raised when a Git operation fails."""


def _git(vault_path: Path, *args: str) -> subprocess.CompletedProcess:
    """Run a git command inside the vault directory."""
    result = subprocess.run(
        ["git", "-C", str(vault_path), *args],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise VaultError(result.stderr.strip() or result.stdout.strip())
    return result


def init_vault(path: Path, remote: str | None = None) -> None:
    """Create a new vault (Git repo) at *path* with a default .gitignore."""
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init")

    gitignore = path / ".gitignore"
    gitignore.write_text(GITIGNORE_TEMPLATE, encoding="utf-8")

    if remote:
        _git(path, "remote", "add", "origin", remote)

    _git(path, "add", ".gitignore")
    _git(path, "commit", "-m", "Init vault")


def is_vault(path: Path) -> bool:
    """Return True if *path* is inside a Git repository."""
    try:
        _git(path, "rev-parse", "--git-dir")
        return True
    except (VaultError, FileNotFoundError):
        return False


def has_remote(vault_path: Path) -> bool:
    """Return True if the vault has at least one remote configured."""
    result = _git(vault_path, "remote")
    return bool(result.stdout.strip())


def commit_file(vault_path: Path, filepath: Path) -> None:
    """Stage and commit a single file inside the vault."""
    relative = filepath.relative_to(vault_path)
    _git(vault_path, "add", str(relative))
    _git(vault_path, "commit", "-m", f"Add: {filepath.name}")


def sync(vault_path: Path) -> None:
    """Pull (rebase) then push to the remote."""
    result = _git(vault_path, "branch", "--show-current")
    branch = result.stdout.strip() or "main"

    try:
        _git(vault_path, "pull", "--rebase", "origin", branch)
    except VaultError as exc:
        raise VaultError(
            f"Merge conflict during pull. Resolve manually in {vault_path} "
            "then run 'ampersand vault sync' again."
        ) from exc

    _git(vault_path, "push", "origin", branch)
