from datetime import datetime, timezone

from ampersand.converter import to_markdown
from ampersand.models import CapturedContent, ContentType


def test_to_markdown_includes_sender_email_when_present() -> None:
    content = CapturedContent(
        url="email://msg-id/example",
        title="Weekly Update",
        content_markdown="Hello world",
        content_type=ContentType.NEWSLETTER,
        author="Example Sender",
        sender_email="team@example.com",
        captured_at=datetime(2026, 4, 2, 12, 0, tzinfo=timezone.utc),
    )

    markdown = to_markdown(content)

    assert "sender_email: team@example.com" in markdown
    assert "# Weekly Update" in markdown
