"""CLI entry point for Ampersand."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import typer

from ampersand_core.converter import to_markdown
from ampersand_core.email_parser import parse_eml_file
from ampersand_core.extractor import extract_article, is_linkedin_url, is_youtube_url
from ampersand_core.feed import parse_feed
from ampersand_core.imap import fetch_unseen, watch
from ampersand_core.newsletter_filter import get_sender_email, is_newsletter
from ampersand_core.youtube import extract_youtube

from ampersand import __version__
from ampersand.backend_bridge import content_to_backend_args, get_backend
from ampersand.config import (
    add_email_account,
    clear_backend_config,
    load_backend_config,
    load_config,
    load_email_accounts,
    load_email_config,
    remove_email_account,
    save_backend_config,
    save_email_config,
    set_value,
)
from ampersand.log_setup import setup_logging
from ampersand.state import AppState
from ampersand.vault import VaultError, commit_file, has_remote, init_vault, is_vault, sync

app = typer.Typer(
    name="ampersand",
    help="Capture anything from the web as markdown you own.",
    add_completion=False,
)

feed_app = typer.Typer(help="Manage RSS/Atom feed subscriptions.")
app.add_typer(feed_app, name="feed")

email_app = typer.Typer(help="Capture newsletters via email.")
app.add_typer(email_app, name="email")

vault_app = typer.Typer(
    help="Configure where the CLI writes (vault backend) and manage the optional git layer."
)
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


def _save(content, *, quiet: bool = False) -> bool:
    """POST a CapturedContent to the configured vault backend.

    Errors out if no backend is configured — the CLI is HTTP-first now,
    no silent local-folder fallback. Run `ampersand vault backend set-http
    <url> --api-key-env KEY` (or `set-store <path>`) once to configure.
    """
    backend = get_backend()
    if backend is None:
        typer.echo(
            "Error: no vault backend configured. Run one of:\n"
            "  ampersand vault backend set-http <url> --api-key-env AMPERSAND_API_KEY\n"
            "  ampersand vault backend set-store <path>",
            err=True,
        )
        raise typer.Exit(code=1)

    body, fm = content_to_backend_args(content)
    try:
        doc = backend.create(body, fm)
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"  Error: backend create failed: {exc}", err=True)
        return False
    finally:
        try:
            backend.close()
        except Exception:  # noqa: BLE001
            pass

    if not quiet:
        label = doc.get("title") or content.title
        typer.echo(f"  Saved: {doc.get('id')} — {label}", err=True)
    return True


@app.command()
def capture(
    url: str = typer.Argument(help="URL to capture."),
    stdout: bool = typer.Option(
        False,
        "--stdout",
        help="Print markdown to stdout instead of saving to the vault.",
    ),
) -> None:
    """Capture a URL and save it to the configured vault."""
    try:
        content = _capture_url(url)
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(code=1)

    if stdout:
        typer.echo(to_markdown(content))
    else:
        _save(content)


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
    """Sync all subscribed feeds and capture new items to the configured vault."""
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
                if _save(content, quiet=False):
                    state.mark_captured(entry.url)
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
    name: str | None = typer.Option(None, "--name", help="Friendly label for logs (defaults to the email)."),
) -> None:
    """Add an IMAP email account for newsletter capture.

    Multiple accounts can coexist — call setup once per inbox. Passing an
    email that already exists replaces that account's credentials.
    """
    add_email_account(
        server=server,
        email_addr=email_addr,
        password=password,
        port=port,
        mailbox=mailbox,
        name=name,
    )
    typer.echo(f"Account added: {email_addr} ({server})")
    total = len(load_email_accounts())
    typer.echo(f"Configured accounts: {total}. Run 'ampersand email sync' or 'ampersand email watch'.")


@email_app.command("list")
def email_list() -> None:
    """List configured IMAP accounts."""
    accounts = load_email_accounts()
    if not accounts:
        typer.echo("No accounts configured. Run 'ampersand email setup'.")
        return
    for a in accounts:
        label = a.get("name") or a.get("email")
        typer.echo(f"  {label}  ({a.get('email')} on {a.get('server')}:{a.get('port')}  mailbox={a.get('mailbox')})")


@email_app.command("rm")
def email_rm(
    email_addr: str = typer.Argument(help="Email address of the account to remove."),
) -> None:
    """Remove an IMAP account from the config."""
    if remove_email_account(email_addr):
        typer.echo(f"Removed: {email_addr}")
    else:
        typer.echo(f"Not configured: {email_addr}", err=True)
        raise typer.Exit(code=1)


def _make_email_filter(state: AppState, state_lock=None):
    """Build a filter callback that checks allowlist + newsletter heuristics.

    `state_lock` is optional — pass one (threading.Lock) when running
    multiple accounts in parallel so the auto-grown allowlist doesn't
    race on the underlying JSON state file.
    """
    from contextlib import nullcontext
    from email.message import EmailMessage

    guard = state_lock if state_lock is not None else nullcontext()

    def email_filter(msg: EmailMessage) -> bool:
        try:
            sender = get_sender_email(msg)
        except Exception:
            # Can't parse sender — capture aggressively rather than skip
            return True
        with guard:
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
def email_sync() -> None:
    """Fetch and capture unread newsletters across every configured IMAP account.

    Each account runs in its own thread — N inboxes fetch in parallel.
    State writes (allowlist, captured-URL set) are serialized by a shared
    lock so the per-account workers can't race on the JSON state file.
    """
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    accounts = load_email_accounts()
    if not accounts:
        typer.echo("No email accounts configured. Run 'ampersand email setup' first.", err=True)
        raise typer.Exit(code=1)

    state = AppState()
    state_lock = threading.Lock()
    typer.echo(f"Checking {len(accounts)} account(s) for new emails...", err=True)

    def _run_one(account: dict) -> tuple[str, int, str | None]:
        label = account.get("name") or account.get("email") or "imap"
        captured = 0
        try:
            for uid, content in fetch_unseen(account, email_filter=_make_email_filter(state, state_lock)):
                with state_lock:
                    if state.is_captured(content.url):
                        continue
                if _save(content, quiet=True):
                    with state_lock:
                        state.mark_captured(content.url)
                    captured += 1
                    typer.echo(f"  [{label}] [{captured}] {content.title}", err=True)
        except Exception as exc:  # noqa: BLE001
            return label, captured, str(exc)
        return label, captured, None

    total = 0
    errors: list[tuple[str, str]] = []
    with ThreadPoolExecutor(max_workers=max(len(accounts), 1)) as pool:
        futures = [pool.submit(_run_one, a) for a in accounts]
        for fut in as_completed(futures):
            label, captured, err = fut.result()
            total += captured
            if err:
                errors.append((label, err))
                typer.echo(f"  [{label}] error: {err}", err=True)

    if errors and total == 0:
        raise typer.Exit(code=1)
    if total == 0:
        typer.echo("No new emails.", err=True)
    else:
        typer.echo(f"Done: captured {total} newsletter(s) across {len(accounts)} account(s).", err=True)


@email_app.command("watch")
def email_watch(
    poll_interval: int = typer.Option(
        30,
        "--interval",
        help="Poll interval in seconds (used when IDLE is not supported).",
    ),
) -> None:
    """Watch every configured mailbox in real-time (IMAP IDLE, one thread per account).

    Spawns N daemon threads — one per configured account — that each run
    the reconnect-forever IDLE/poll loop. Ctrl+C interrupts the main
    thread and the daemons die on process exit. State mutations are
    serialized by a shared lock.
    """
    import threading

    accounts = load_email_accounts()
    if not accounts:
        typer.echo("No email accounts configured. Run 'ampersand email setup' first.", err=True)
        raise typer.Exit(code=1)

    state = AppState()
    state_lock = threading.Lock()
    labels = [a.get("name") or a.get("email") for a in accounts]
    typer.echo(f"Watching {len(accounts)} account(s): {', '.join(labels)} (Ctrl+C to stop)", err=True)

    def _make_on_email(label: str):
        def on_email(content):
            with state_lock:
                if state.is_captured(content.url):
                    return
            if _save(content):
                with state_lock:
                    state.mark_captured(content.url)
                typer.echo(f"  [{label}] {content.title}", err=True)
        return on_email

    def _run_account(account: dict):
        label = account.get("name") or account.get("email")
        try:
            watch(
                account,
                on_email=_make_on_email(label),
                poll_interval=poll_interval,
                email_filter=_make_email_filter(state, state_lock),
            )
        except Exception as exc:  # noqa: BLE001
            typer.echo(f"  [{label}] watch crashed: {exc}", err=True)

    threads: list[threading.Thread] = []
    for account in accounts:
        t = threading.Thread(target=_run_account, args=(account,), daemon=True)
        t.start()
        threads.append(t)

    try:
        # Hold the main thread; daemons run forever, Ctrl+C kills them.
        while any(t.is_alive() for t in threads):
            for t in threads:
                t.join(timeout=1.0)
    except KeyboardInterrupt:
        typer.echo("\nStopped watching.", err=True)


@email_app.command("parse")
def email_parse(
    file: Path = typer.Argument(help="Path to .eml file."),
    stdout: bool = typer.Option(
        False,
        "--stdout",
        help="Print markdown to stdout instead of saving to the vault.",
    ),
) -> None:
    """Parse a local .eml file into the configured vault."""
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
        _save(content)


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


# ── Backend config (where capture flows write) ──────────────────────


backend_app = typer.Typer(help="Configure where capture flows write (HTTP remote or local store).")
vault_app.add_typer(backend_app, name="backend")


@backend_app.command("show")
def backend_show() -> None:
    """Show the configured backend (or 'none' for legacy local writes)."""
    cfg = load_backend_config()
    if not cfg:
        typer.echo("No backend configured. Captures use the legacy local-folder path.")
        raise typer.Exit(code=0)
    import json as _json

    typer.echo(_json.dumps(cfg, indent=2))


@backend_app.command("set-http")
def backend_set_http(
    url: str = typer.Argument(help="Server URL, e.g. http://68.183.29.223 or https://vault.example.com"),
    api_key: str | None = typer.Option(
        None, "--api-key", help="Bearer token. Prefer --api-key-env to keep the key out of files."
    ),
    api_key_env: str | None = typer.Option(
        None, "--api-key-env", help="Name of the env var holding the bearer token."
    ),
) -> None:
    """Point capture flows at a remote ampersand-server (HTTPBackend)."""
    if not api_key and not api_key_env:
        typer.echo("Provide either --api-key or --api-key-env.", err=True)
        raise typer.Exit(code=1)
    cfg = {"kind": "http", "http": {"url": url.rstrip("/")}}
    if api_key:
        cfg["http"]["api_key"] = api_key
    if api_key_env:
        cfg["http"]["api_key_env"] = api_key_env
    save_backend_config(cfg)
    typer.echo(f"Backend set: http -> {url}")


@backend_app.command("set-store")
def backend_set_store(
    path: Path = typer.Argument(help="Local vault data dir, e.g. /var/lib/ampersand/vault"),
) -> None:
    """Point capture flows at a local MarkdownStore (StoreBackend)."""
    cfg = {"kind": "store", "store": {"path": str(path.expanduser())}}
    save_backend_config(cfg)
    typer.echo(f"Backend set: store -> {path}")


@backend_app.command("clear")
def backend_clear() -> None:
    """Remove backend config. Capture flows will refuse to run until reconfigured."""
    clear_backend_config()
    typer.echo(
        "Backend cleared. Capture flows will error out until a backend is set "
        "again with `ampersand vault backend set-http|set-store ...`."
    )
