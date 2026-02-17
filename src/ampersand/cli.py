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
from ampersand.imap import fetch_unseen, load_email_config, save_email_config, watch
from ampersand.state import AppState
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


# ── Single URL capture ────────────────────────────────────────────────


def _capture_url(url: str):
    """Extract content from a single URL (article or YouTube)."""
    if is_youtube_url(url):
        typer.echo("Extracting YouTube video...", err=True)
        return extract_youtube(url)
    else:
        typer.echo(f"Extracting article...", err=True)
        return extract_article(url)


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
        filepath = save_markdown(content, output, filename)
        typer.echo(f"Saved: {filepath}", err=True)


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
                filepath = save_markdown(content, output)
                state.mark_captured(entry.url)
                typer.echo(f"  Saved: {filepath}", err=True)
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


@email_app.command("sync")
def email_sync(
    output: Path = typer.Option(
        Path("."),
        "--output",
        "-o",
        help="Output directory for captured .md files.",
    ),
) -> None:
    """Fetch and capture all unread emails from configured mailbox."""
    config = load_email_config()
    if not config:
        typer.echo("No email configured. Run 'ampersand email setup' first.", err=True)
        raise typer.Exit(code=1)

    state = AppState()
    typer.echo("Checking for new emails...", err=True)

    try:
        results = fetch_unseen(config)
    except Exception as e:
        typer.echo(f"Error connecting to mailbox: {e}", err=True)
        raise typer.Exit(code=1)

    if not results:
        typer.echo("No new emails.", err=True)
        return

    captured = 0
    for uid, content in results:
        if state.is_captured(content.url):
            continue
        filepath = save_markdown(content, output)
        state.mark_captured(content.url)
        typer.echo(f"Saved: {filepath}", err=True)
        captured += 1

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
    """Watch mailbox for new emails in real-time (IMAP IDLE)."""
    config = load_email_config()
    if not config:
        typer.echo("No email configured. Run 'ampersand email setup' first.", err=True)
        raise typer.Exit(code=1)

    state = AppState()
    typer.echo(f"Watching {config['email']} for new emails... (Ctrl+C to stop)", err=True)

    def on_email(content):
        if state.is_captured(content.url):
            return
        filepath = save_markdown(content, output)
        state.mark_captured(content.url)
        typer.echo(f"Saved: {filepath}", err=True)

    try:
        watch(config, on_email=on_email, poll_interval=poll_interval)
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
        filepath = save_markdown(content, output)
        typer.echo(f"Saved: {filepath}", err=True)
