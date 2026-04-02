"""Content extraction from URLs using trafilatura."""

from __future__ import annotations

import logging
import re

import httpx
import trafilatura

from ampersand.models import CapturedContent, ContentType

logger = logging.getLogger(__name__)

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_YOUTUBE_PATTERNS = [
    re.compile(r"(?:youtube\.com/watch\?v=|youtu\.be/)([\w-]{11})"),
    re.compile(r"youtube\.com/embed/([\w-]{11})"),
    re.compile(r"youtube\.com/shorts/([\w-]{11})"),
]


def is_youtube_url(url: str) -> bool:
    return any(p.search(url) for p in _YOUTUBE_PATTERNS)


def extract_youtube_id(url: str) -> str | None:
    for p in _YOUTUBE_PATTERNS:
        m = p.search(url)
        if m:
            return m.group(1)
    return None


def _fetch_with_playwright(url: str) -> str:
    """Fetch a page using a headless Chromium browser (JS-rendered)."""
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            # Give JS a moment to render dynamic content
            page.wait_for_timeout(3000)
            html = page.content()
            browser.close()
        return html
    except Exception as exc:
        message = str(exc)
        if "Executable doesn't exist" in message or "browserType.launch" in message:
            raise ValueError(
                "Playwright Chromium is not installed. Run 'playwright install chromium' and try again."
            ) from exc
        raise


def _fetch_url(url: str) -> str:
    """Fetch URL HTML with three-tier fallback: trafilatura → httpx → playwright."""
    # Tier 1: trafilatura (fast, lightweight)
    downloaded = trafilatura.fetch_url(url)
    if downloaded:
        return downloaded
    logger.debug("trafilatura failed for %s, trying httpx", url)

    # Tier 2: httpx with browser headers
    try:
        resp = httpx.get(url, headers=_BROWSER_HEADERS, follow_redirects=True, timeout=30)
        resp.raise_for_status()
        if resp.text and len(resp.text.strip()) > 200:
            return resp.text
        logger.debug("httpx returned thin content for %s, trying playwright", url)
    except httpx.HTTPError as exc:
        logger.debug("httpx failed for %s: %s, trying playwright", url, exc)

    # Tier 3: headless browser (handles JS-rendered pages)
    logger.info("Using playwright for %s", url)
    return _fetch_with_playwright(url)


def extract_article(url: str) -> CapturedContent:
    """Fetch a URL and extract its article content as markdown."""
    downloaded = _fetch_url(url)
    if not downloaded:
        raise ValueError(f"Failed to fetch URL: {url}")

    # Extract main text as markdown
    text = trafilatura.extract(
        downloaded,
        output_format="markdown",
        include_links=True,
        include_images=True,
        include_tables=True,
    )
    if not text:
        raise ValueError(f"Failed to extract content from: {url}")

    # Clean up empty image tags and table artifacts
    text = re.sub(r"!\[\]\(\)\s*\|?\s*", "", text)
    text = re.sub(r"^\|?\s*\n", "", text, flags=re.MULTILINE)
    text = text.lstrip("\n")

    # Extract metadata
    metadata = trafilatura.extract_metadata(downloaded)

    title = "Untitled"
    author = None
    if metadata:
        title = metadata.title or title
        author = metadata.author

    return CapturedContent(
        url=url,
        title=title,
        content_markdown=text,
        content_type=ContentType.ARTICLE,
        author=author,
    )
