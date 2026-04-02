import importlib
import sys
import types

import pytest


def test_fetch_with_playwright_explains_missing_browser(monkeypatch) -> None:
    class FakeChromium:
        def launch(self, headless: bool = True):
            raise RuntimeError("Executable doesn't exist at /tmp/chromium")

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeManager:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, exc_type, exc, tb):
            return False

    sys.modules.pop("ampersand.extractor", None)
    monkeypatch.setitem(sys.modules, "trafilatura", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "playwright.sync_api",
        types.SimpleNamespace(sync_playwright=lambda: FakeManager()),
    )
    extractor = importlib.import_module("ampersand.extractor")

    with pytest.raises(ValueError, match="playwright install chromium"):
        extractor._fetch_with_playwright("https://example.com")
