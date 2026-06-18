# Server Architecture — Blockers & Plan

## Context
Amperstand currently runs as a CLI. We want to wrap it in a server to accept captures from multiple mediums: Telegram bot, browser extension, API, etc.

## Current State: What's Already Good
- **CLI is a thin wrapper** — no core module imports typer. FastAPI can call the same functions directly.
- **Core functions are pure-ish** — `extract_article()`, `to_markdown()`, `parse_email_bytes()`, `is_newsletter()` take input and return output.
- **Paths are configurable** — `AppState` and config functions accept `state_dir` parameter, so multi-tenant isolation is possible without refactoring signatures.

## Blockers

### Critical: State is not concurrency-safe
`AppState` (`state.py`) is a JSON file with read-modify-write and no locking. Two concurrent captures will clobber each other:

```
Client A loads state.json -> captured = [url1, url2]
Client B loads state.json -> captured = [url1, url2]
Client A: mark_captured(url3) -> writes [url1, url2, url3]
Client B: mark_captured(url4) -> writes [url1, url2, url4]  <- url3 lost
```

**Fix:** Replace with SQLite (WAL mode). Longer term, Postgres for multi-machine.

### High: Blocking I/O everywhere
- **Vault git ops** (`vault.py`) — `subprocess.run()` with no timeout. `sync()` does `git pull --rebase && git push` which can hang indefinitely. Needs timeouts + background task queue.
- **IMAP `watch()`** (`imap.py`) — infinite blocking loop, not usable inside a web worker. Must become a separate long-running service.
- **`trafilatura.fetch_url()`** (`extractor.py`) — synchronous HTTP, no timeout.

### Medium: Config/paths default to user home
`DEFAULT_STATE_DIR = Path.home() / ".amperstand"` works for CLI but not for a multi-tenant server. Server must pass explicit `state_dir` per user/client.

## Sequenced Plan
1. Replace `state.json` with SQLite (unblocks concurrency)
2. Add timeouts to vault subprocess calls (low effort, high safety)
3. Build a thin FastAPI app wrapping existing capture functions
4. Move IMAP watch + vault sync to background workers
5. Add intake endpoints for new mediums (Telegram webhook, browser extension POST)
