"""Tests for collectors/rss_generic.py — helpers and collector (mocked)."""
import hashlib
import time
from unittest.mock import MagicMock, patch

from collectors.rss_generic import (
    RSSCollector,
    _entry_author,
    _entry_body,
    _extract_links,
    _stable_guid,
    _to_iso,
)

_site_name = RSSCollector._site_name


class TestEntryBody:
    def test_string_body(self):
        entry = {"summary": "Hello world"}
        assert _entry_body(entry) == "Hello world"

    def test_content_list(self):
        entry = {"content": [{"value": "From content list"}]}
        assert _entry_body(entry) == "From content list"

    def test_content_string(self):
        entry = {"content": "From content string"}
        assert _entry_body(entry) == "From content string"

    def test_description_fallback(self):
        entry = {"description": "From description"}
        assert _entry_body(entry) == "From description"

    def test_no_body(self):
        entry = {}
        assert _entry_body(entry) is None

    def test_content_list_empty(self):
        entry = {"content": []}
        assert _entry_body(entry) is None


class TestEntryAuthor:
    def test_author_field(self):
        entry = {"author": "John"}
        assert _entry_author(entry) == "John"

    def test_authors_list(self):
        entry = {"authors": [{"name": "Jane"}]}
        assert _entry_author(entry) == "Jane"

    def test_no_author(self):
        entry = {}
        assert _entry_author(entry) is None

    def test_empty_authors_list(self):
        entry = {"authors": []}
        assert _entry_author(entry) is None


class TestToIso:
    def test_valid_tuple(self):
        t = time.struct_time((2026, 1, 1, 0, 0, 0, 0, 0, 0))
        assert _to_iso(t) == "2026-01-01T00:00:00Z"

    def test_none_returns_none(self):
        assert _to_iso(None) is None

    def test_invalid_tuple_returns_none(self):
        assert _to_iso("not a tuple") is None

    def test_incomplete_tuple_returns_none(self):
        assert _to_iso((2026,)) is None


class TestStableGuid:
    def test_deterministic(self):
        g1 = _stable_guid("site1", "guid1")
        g2 = _stable_guid("site1", "guid1")
        assert g1 == g2

    def test_different_inputs(self):
        g1 = _stable_guid("site1", "guid1")
        g2 = _stable_guid("site1", "guid2")
        assert g1 != g2

    def test_different_sites(self):
        g1 = _stable_guid("site1", "guid1")
        g2 = _stable_guid("site2", "guid1")
        assert g1 != g2

    def test_is_md5(self):
        g = _stable_guid("site", "guid")
        assert len(g) == 32
        # Verify it's actually md5
        expected = hashlib.md5("site|guid".encode()).hexdigest()
        assert g == expected


class TestExtractLinks:
    def test_finds_urls(self):
        text = "Visit https://example.com and http://test.org"
        links = _extract_links(text)
        assert len(links) == 2
        assert "https://example.com" in links
        assert "http://test.org" in links

    def test_deduplicates(self):
        text = "https://example.com and again https://example.com"
        links = _extract_links(text)
        assert len(links) == 1

    def test_none_returns_empty(self):
        assert _extract_links(None) == []

    def test_empty_returns_empty(self):
        assert _extract_links("") == []

    def test_no_urls(self):
        assert _extract_links("just plain text") == []

    def test_max_20(self):
        text = " ".join(f"https://example.com/{i}" for i in range(30))
        links = _extract_links(text)
        assert len(links) == 20


class TestSiteName:
    def test_feed_has_title(self):
        # feedparser uses FeedParserDict which supports attribute access
        parsed = MagicMock()
        parsed.feed = MagicMock()
        parsed.feed.get.return_value = "My Blog"
        parsed.feed.title = "My Blog"
        assert _site_name(parsed, "https://example.com/feed") == "My Blog"

    def test_feed_no_title_uses_host(self):
        parsed = MagicMock()
        parsed.feed = MagicMock()
        parsed.feed.get.return_value = None
        parsed.feed.title = None  # AttributeError won't happen because .get returns None first
        # Actually _site_name uses .get("title") first, then .title as attribute
        # When feed is a MagicMock, .get("title") returns a MagicMock (truthy)
        # So we need to make .get return None
        parsed.feed.__getitem__ = MagicMock(side_effect=KeyError)
        assert _site_name(parsed, "https://blog.example.com/feed") == "blog.example.com"

    def test_title_truncated(self):
        parsed = MagicMock()
        parsed.feed = MagicMock()
        long_title = "A" * 100
        parsed.feed.get.return_value = long_title
        parsed.feed.title = long_title
        result = _site_name(parsed, "https://example.com")
        assert len(result) == 60
