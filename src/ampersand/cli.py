"""CLI entry point for Ampersand."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import typer

from ampersand import __version__
from ampersand.converter import save_markdown, to_markdown
from ampersand.email_parser import parse_eml_file
from ampersand.extractor import extract_article, is_youtube_url
from ampersand.feed import parse_feed
from ampersand.config import load_config, load_email_config, save_email_config, set_value
from ampersand.imap import fetch_unseen, watch
from ampersand.log_setup import setup_logging
from ampersand.newsletter_filter import get_sender_email, is_newsletter
from ampersand.state import AppState
from ampersand.vault import VaultError, commit_file, has_remote, init_vault, is_vault, sync
from ampersand.youtube import extract_youtube

app = typer.Typer(
    name="ampersand",
    help="Capture anything from the web as markdown you own.",
    add_completion=False,
)

feed_app = typer.Typer(help="Manage RSS/Atom feed subscriptions.")
app.add_typer(feed_app, name="feed")

email_app = typer.Typer(help="Capture newsletters via email.")
app.add_typer(email_app, name="email")

vault_app = typer.Typer(help="Manage Git-backed vault for collaborative storage.")
app.add_typer(vault_app, name="vault")

config_app = typer.Typer(help="View and update Ampersand configuration.")
app.add_typer(config_app, name="config")


def version_callback(value: bool) -> None:
    if value:
        typer.echo(f"ampersand {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
) -> None:
    """Ampersand — capture anything from the web as markdown you own."""
    setup_logging()


# ── Single URL capture ────────────────────────────────────────────────


def _capture_url(url: str):
    """Extract content from a single URL (article or YouTube)."""
    if is_youtube_url(url):
        typer.echo("Extracting YouTube video...", err=True)
        return extract_youtube(url)
    else:
        typer.echo(f"Extracting article...", err=True)
        return extract_article(url)


def _resolve_output(output: Path) -> tuple[Path, Path | None]:
    """Return (output_dir, vault_path_or_none).

    If the user didn't override --output (still "."), use the configured vault.
    """
    state = AppState()
    vault = state.get_vault()
    vault_path = Path(vault["path"]) if vault else None

    if vault_path and output == Path("."):
        return vault_path, vault_path
    if vault_path and output.resolve().is_relative_to(vault_path.resolve()):
        return output, vault_path
    return output, None


def _try_commit(vault_path: Path | None, filepath: Path) -> None:
    """Commit a file to the vault, logging errors without crashing."""
    if vault_path is None:
        return
    try:
        commit_file(vault_path, filepath)
    except VaultError as exc:
        typer.echo(f"Warning: git commit failed: {exc}", err=True)


@app.command()
def capture(
    url: str = typer.Argument(help="URL to capture."),
    output: Path = typer.Option(
        Path("."),
        "--output",
        "-o",
        help="Output directory for the .md file.",
    ),
    filename: str | None = typer.Option(
        None,
        "--filename",
        "-f",
        help="Custom filename (without extension).",
    ),
    stdout: bool = typer.Option(
        False,
        "--stdout",
        help="Print markdown to stdout instead of saving a file.",
    ),
) -> None:
    """Capture a URL and save it as a markdown file."""
    try:
        content = _capture_url(url)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    if stdout:
        typer.echo(to_markdown(content))
    else:
        output_dir, vault_path = _resolve_output(output)
        filepath = save_markdown(content, output_dir, filename)
        typer.echo(f"Saved: {filepath}", err=True)
        _try_commit(vault_path, filepath)


# ── Feed commands ─────────────────────────────────────────────────────


@feed_app.command("add")
def feed_add(
    url: str = typer.Argument(help="RSS/Atom feed URL."),
    name: str | None = typer.Option(None, "--name", "-n", help="Display name for the feed."),
    tags: list[str] = typer.Option([], "--tag", "-t", help="Tags for this feed (repeatable)."),
) -> None:
    """Subscribe to an RSS/Atom feed."""
    state = AppState()

    if state.get_feed(url):
        typer.echo(f"Already subscribed: {url}", err=True)
        raise typer.Exit(code=1)

    # Fetch feed to validate and get title
    try:
        info = parse_feed(url)
    except Exception as e:
        typer.echo(f"Error parsing feed: {e}", err=True)
        raise typer.Exit(code=1)

    feed_name = name or info.title
    state.add_feed(url, name=feed_name, tags=tags)
    entry_count = len(info.entries) if info.entries else 0
    typer.echo(f"Subscribed: {feed_name} ({entry_count} entries)")


@feed_app.command("remove")
def feed_remove(
    url: str = typer.Argument(help="Feed URL to unsubscribe from."),
) -> None:
    """Unsubscribe from a feed."""
    state = AppState()
    if state.remove_feed(url):
        typer.echo(f"Removed: {url}")
    else:
        typer.echo(f"Not subscribed: {url}", err=True)
        raise typer.Exit(code=1)


@feed_app.command("list")
def feed_list() -> None:
    """List all subscribed feeds."""
    state = AppState()
    feeds = state.list_feeds()

    if not feeds:
        typer.echo("No feeds subscribed. Use 'ampersand feed add <url>' to add one.")
        return

    for url, info in feeds.items():
        tags_str = f"  [{', '.join(info['tags'])}]" if info.get("tags") else ""
        typer.echo(f"  {info['name']}{tags_str}")
        typer.echo(f"    {url}")


@feed_app.command("sync")
def feed_sync(
    output: Path = typer.Option(
        Path("."),
        "--output",
        "-o",
        help="Output directory for captured .md files.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be captured without actually doing it.",
    ),
    limit: int = typer.Option(
        0,
        "--limit",
        "-l",
        help="Max items to capture per feed (0 = all).",
    ),
    feed_url: str | None = typer.Option(
        None,
        "--feed",
        help="Sync only this specific feed URL.",
    ),
) -> None:
    """Sync all subscribed feeds and capture new items."""
    output_dir, vault_path = _resolve_output(output)
    state = AppState()
    feeds = state.list_feeds()

    if feed_url:
        if feed_url not in feeds:
            typer.echo(f"Not subscribed: {feed_url}", err=True)
            raise typer.Exit(code=1)
        feeds = {feed_url: feeds[feed_url]}

    if not feeds:
        typer.echo("No feeds subscribed. Use 'ampersand feed add <url>' to add one.")
        return

    total_captured = 0
    total_skipped = 0

    for url, info in feeds.items():
        typer.echo(f"\nFeed: {info['name']}", err=True)

        try:
            feed_info = parse_feed(url)
        except Exception as e:
            typer.echo(f"  Error: {e}", err=True)
            continue

        entries = feed_info.entries or []
        if limit > 0:
            entries = entries[:limit]

        for entry in entries:
            if state.is_captured(entry.url):
                total_skipped += 1
                continue

            if dry_run:
                date_str = entry.published.strftime("%Y-%m-%d") if entry.published else "no date"
                typer.echo(f"  [new] {entry.title} ({date_str})")
                total_captured += 1
                continue

            try:
                content = _capture_url(entry.url)
                # Use feed entry metadata as fallback
                if entry.author and not content.author:
                    content.author = entry.author
                filepath = save_markdown(content, output_dir)
                state.mark_captured(entry.url)
                typer.echo(f"  Saved: {filepath}", err=True)
                _try_commit(vault_path, filepath)
                total_captured += 1
            except Exception as e:
                typer.echo(f"  Error capturing {entry.url}: {e}", err=True)

    action = "would capture" if dry_run else "captured"
    typer.echo(f"\nDone: {action} {total_captured}, skipped {total_skipped} already captured.", err=True)


# ── Email commands ────────────────────────────────────────────────────


@email_app.command("setup")
def email_setup(
    server: str = typer.Option(..., "--server", "-s", prompt="IMAP server (e.g. imap.gmail.com)"),
    email_addr: str = typer.Option(..., "--email", "-e", prompt="Email address"),
    password: str = typer.Option(..., "--password", "-p", prompt="Password (app password for Gmail)", hide_input=True),
    port: int = typer.Option(993, "--port", help="IMAP port."),
    mailbox: str = typer.Option("INBOX", "--mailbox", help="Mailbox to monitor."),
) -> None:
    """Configure IMAP email account for newsletter capture."""
    save_email_config(
        server=server,
        email_addr=email_addr,
        password=password,
        port=port,
        mailbox=mailbox,
    )
    typer.echo(f"Email configured: {email_addr} on {server}")
    typer.echo("Run 'ampersand email sync' to fetch newsletters, or 'ampersand email watch' for real-time.")


def _make_email_filter(state: AppState):
    """Build a filter callback that checks allowlist + newsletter heuristics."""
    from email.message import EmailMessage

    def email_filter(msg: EmailMessage) -> bool:
        try:
            sender = get_sender_email(msg)
        except Exception:
            # Can't parse sender — capture aggressively rather than skip
            return True
        if state.is_sender_allowed(sender):
            return True
        if is_newsletter(msg):
            # Auto-add sender so the allowlist grows over time
            state.add_sender(sender)
            return True
        typer.echo(f"Skipped: {sender} (not detected as newsletter)", err=True)
        return False

    return email_filter


@email_app.command("allow")
def email_allow(
    sender: str = typer.Argument(help="Email address or @domain to allow."),
) -> None:
    """Add a sender to the newsletter allowlist."""
    state = AppState()
    state.add_sender(sender)
    typer.echo(f"Allowed: {sender}")


@email_app.command("block")
def email_block(
    sender: str = typer.Argument(help="Email address or @domain to remove."),
) -> None:
    """Remove a sender from the newsletter allowlist."""
    state = AppState()
    if state.remove_sender(sender):
        typer.echo(f"Removed: {sender}")
    else:
        typer.echo(f"Not in allowlist: {sender}", err=True)
        raise typer.Exit(code=1)


@email_app.command("senders")
def email_senders() -> None:
    """List all allowed newsletter senders."""
    state = AppState()
    senders = state.list_senders()
    if not senders:
        typer.echo("No senders in allowlist. Use 'ampersand email allow <sender>' to add one.")
        return
    for s in senders:
        typer.echo(f"  {s}")


@email_app.command("sync")
def email_sync(
    output: Path = typer.Option(
        Path("."),
        "--output",
        "-o",
        help="Output directory for captured .md files.",
    ),
) -> None:
    """Fetch and capture all unread newsletters from configured mailbox."""
    config = load_email_config()
    if not config:
        typer.echo("No email configured. Run 'ampersand email setup' first.", err=True)
        raise typer.Exit(code=1)

    output_dir, vault_path = _resolve_output(output)
    state = AppState()
    typer.echo("Checking for new emails...", err=True)

    captured = 0
    try:
        for uid, content in fetch_unseen(config, email_filter=_make_email_filter(state)):
            if state.is_captured(content.url):
                continue
            filepath = save_markdown(content, output_dir)
            state.mark_captured(content.url)
            captured += 1
            typer.echo(f"  [{captured}] Saved: {filepath}", err=True)
            _try_commit(vault_path, filepath)
    except Exception as e:
        typer.echo(f"Error during email sync: {e}", err=True)
        if captured == 0:
            raise typer.Exit(code=1)

    if captured == 0:
        typer.echo("No new emails.", err=True)
    else:
        typer.echo(f"Done: captured {captured} newsletter(s).", err=True)


@email_app.command("watch")
def email_watch(
    output: Path = typer.Option(
        Path("."),
        "--output",
        "-o",
        help="Output directory for captured .md files.",
    ),
    poll_interval: int = typer.Option(
        30,
        "--interval",
        help="Poll interval in seconds (used when IDLE is not supported).",
    ),
) -> None:
    """Watch mailbox for new newsletters in real-time (IMAP IDLE)."""
    config = load_email_config()
    if not config:
        typer.echo("No email configured. Run 'ampersand email setup' first.", err=True)
        raise typer.Exit(code=1)

    output_dir, vault_path = _resolve_output(output)
    state = AppState()
    typer.echo(f"Watching {config['email']} for new emails... (Ctrl+C to stop)", err=True)

    def on_email(content):
        if state.is_captured(content.url):
            return
        filepath = save_markdown(content, output_dir)
        state.mark_captured(content.url)
        typer.echo(f"Saved: {filepath}", err=True)
        _try_commit(vault_path, filepath)

    try:
        watch(
            config,
            on_email=on_email,
            poll_interval=poll_interval,
            email_filter=_make_email_filter(state),
        )
    except KeyboardInterrupt:
        typer.echo("\nStopped watching.", err=True)


@email_app.command("parse")
def email_parse(
    file: Path = typer.Argument(help="Path to .eml file."),
    output: Path = typer.Option(
        Path("."),
        "--output",
        "-o",
        help="Output directory for the .md file.",
    ),
    stdout: bool = typer.Option(
        False,
        "--stdout",
        help="Print markdown to stdout instead of saving a file.",
    ),
) -> None:
    """Parse a local .eml file into markdown."""
    if not file.exists():
        typer.echo(f"File not found: {file}", err=True)
        raise typer.Exit(code=1)

    try:
        content = parse_eml_file(file)
    except Exception as e:
        typer.echo(f"Error parsing email: {e}", err=True)
        raise typer.Exit(code=1)

    if stdout:
        typer.echo(to_markdown(content))
    else:
        output_dir, vault_path = _resolve_output(output)
        filepath = save_markdown(content, output_dir)
        typer.echo(f"Saved: {filepath}", err=True)
        _try_commit(vault_path, filepath)


# ── Config commands ──────────────────────────────────────────────────


@config_app.command("show")
def config_show() -> None:
    """Print current configuration as JSON."""
    import json

    config = load_config()
    typer.echo(json.dumps(config, indent=2))


@config_app.command("set")
def config_set(
    key: str = typer.Argument(help="Dotted config key (e.g. logging.level)."),
    value: str = typer.Argument(help="Value to set."),
) -> None:
    """Set a configuration value (e.g. ampersand config set logging.level DEBUG)."""
    try:
        set_value(key, value)
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Set {key} = {value}")


# ── Vault commands ───────────────────────────────────────────────────


@vault_app.command("init")
def vault_init(
    path: Path = typer.Argument(help="Directory to initialize as a vault."),
    remote: str | None = typer.Option(
        None,
        "--remote",
        "-r",
        help="Git remote URL to add as origin.",
    ),
) -> None:
    """Initialize a new Git-backed vault and set it as default."""
    try:
        init_vault(path, remote=remote)
    except VaultError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)

    state = AppState()
    state.set_vault(str(path.resolve()))
    typer.echo(f"Vault initialized: {path.resolve()}")
    if remote:
        typer.echo(f"Remote: {remote}")


@vault_app.command("sync")
def vault_sync() -> None:
    """Pull and push the current vault to its remote."""
    state = AppState()
    vault = state.get_vault()
    if not vault:
        typer.echo("No vault configured. Run 'ampersand vault init <path>' first.", err=True)
        raise typer.Exit(code=1)

    vault_path = Path(vault["path"])
    if not has_remote(vault_path):
        typer.echo("Vault has no remote configured. Add one with: git -C <vault> remote add origin <url>", err=True)
        raise typer.Exit(code=1)

    try:
        sync(vault_path)
        typer.echo("Vault synced.")
    except VaultError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1)


@vault_app.command("status")
def vault_status() -> None:
    """Show current vault path and Git status."""
    state = AppState()
    vault = state.get_vault()
    if not vault:
        typer.echo("No vault configured.")
        return

    vault_path = Path(vault["path"])
    typer.echo(f"Vault: {vault_path}")
    typer.echo(f"Auto-sync: {vault.get('auto_sync', False)}")

    if not is_vault(vault_path):
        typer.echo("Warning: path is not a Git repository.", err=True)
        return

    from ampersand.vault import _git

    # Uncommitted changes
    result = _git(vault_path, "status", "--porcelain")
    uncommitted = len([l for l in result.stdout.splitlines() if l.strip()])
    typer.echo(f"Uncommitted files: {uncommitted}")

    # Unpushed commits
    if has_remote(vault_path):
        try:
            result = _git(vault_path, "rev-list", "--count", "@{u}..HEAD")
            typer.echo(f"Unpushed commits: {result.stdout.strip()}")
        except VaultError:
            typer.echo("Unpushed commits: unknown (no upstream branch)")
    else:
        typer.echo("Remote: none")


@vault_app.command("unset")
def vault_unset() -> None:
    """Remove vault from config (does not delete files)."""
    state = AppState()
    if not state.get_vault():
        typer.echo("No vault configured.", err=True)
        raise typer.Exit(code=1)

    state.clear_vault()
    typer.echo("Vault unset. Captures will save to current directory.")
