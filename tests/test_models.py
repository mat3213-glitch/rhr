"""Tests for models.py — strip_html, RawItem, Signal."""
from models import RawItem, Signal, strip_html, utcnow_iso


class TestStripHtml:
    def test_none_returns_none(self):
        assert strip_html(None) is None

    def test_empty_string_returns_empty_or_none(self):
        assert strip_html("") == ""
        assert strip_html("   ") is None

    def test_tags_only_returns_none(self):
        assert strip_html("<b></b>") is None
        assert strip_html("<div><br/></div>") is None

    def test_plain_text_unchanged(self):
        assert strip_html("hello world") == "hello world"

    def test_strips_tags(self):
        assert strip_html("<b>bold</b> text") == "bold text"

    def test_nested_tags(self):
        assert strip_html("<div><p>line1</p><p>line2</p></div>") == "line1 line2"

    def test_html_entities(self):
        assert strip_html("a &amp; b &lt; c") == "a & b < c"

    def test_collapses_whitespace(self):
        assert strip_html("  hello   \n  world  ") == "hello world"

    def test_mixed_content(self):
        html = "<p>This is <b>bold</b> and <i>italic</i>.</p>"
        result = strip_html(html)
        # Tags are replaced with spaces, so there's a space before the dot
        assert "bold" in result
        assert "italic" in result
        assert "This is" in result


class TestUtcnowIso:
    def test_format(self):
        ts = utcnow_iso()
        assert ts.endswith("Z")
        assert "T" in ts
        assert len(ts) == 20  # 2026-06-20T11:30:00Z


class TestRawItem:
    def test_minimal_construction(self):
        item = RawItem(source="hackernews", source_item_id="123")
        assert item.source == "hackernews"
        assert item.source_item_id == "123"
        assert item.url is None
        assert item.title is None
        assert item.matched_groups == []
        assert item.embedded_links == []
        assert item.fetched_at.endswith("Z")

    def test_full_construction(self):
        item = RawItem(
            source="rss",
            source_item_id="abc",
            url="https://example.com/post",
            title="Test Post",
            body_text="Some body",
            author="tester",
            published_at="2026-01-01T00:00:00Z",
            language="en",
            points=42,
            comments_count=10,
            matched_groups=["money_making"],
            embedded_links=["https://example.com"],
        )
        assert item.points == 42
        assert item.matched_groups == ["money_making"]

    def test_model_dump(self):
        item = RawItem(source="hn", source_item_id="1")
        d = item.model_dump()
        assert d["source"] == "hn"
        assert d["matched_groups"] == []
        assert "fetched_at" in d


class TestSignal:
    def test_construction(self):
        sig = Signal(
            source="rss",
            source_item_id="guid1",
            dedup_key="abc123",
        )
        assert sig.dedup_key == "abc123"
        assert sig.l1_status == "new"

    def test_inherits_raw_item(self):
        sig = Signal(
            source="rss",
            source_item_id="guid1",
            dedup_key="key",
            title="Hello",
            points=5,
        )
        assert sig.title == "Hello"
        assert sig.points == 5
