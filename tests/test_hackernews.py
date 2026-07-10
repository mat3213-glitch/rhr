"""Tests for collectors/hackernews.py — _unix_to_iso, _fetch_item (mocked)."""
from unittest.mock import MagicMock

import httpx
import pytest

from collectors.hackernews import HackerNewsCollector, _unix_to_iso


class TestUnixToIso:
    def test_valid_timestamp(self):
        # 2026-01-01T00:00:00Z = 1767225600
        result = _unix_to_iso(1767225600)
        assert result == "2026-01-01T00:00:00Z"

    def test_none_returns_none(self):
        assert _unix_to_iso(None) is None

    def test_zero_returns_none(self):
        assert _unix_to_iso(0) == "1970-01-01T00:00:00Z"


class TestHackerNewsCollectorFetchItem:
    def test_valid_story(self):
        client = MagicMock(spec=httpx.Client)
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "type": "story",
            "title": "Show HN: My Project",
            "url": "https://example.com",
            "by": "tester",
            "time": 1767225600,
            "score": 42,
            "descendants": 10,
        }
        client.get.return_value = response

        item = HackerNewsCollector._fetch_item(client, 123)
        assert item is not None
        assert item.source == "hackernews"
        assert item.source_item_id == "123"
        assert item.title == "Show HN: My Project"
        assert item.url == "https://example.com"
        assert item.author == "tester"
        assert item.points == 42
        assert item.comments_count == 10

    def test_dead_item_returns_none(self):
        client = MagicMock(spec=httpx.Client)
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"type": "story", "dead": True}
        client.get.return_value = response

        assert HackerNewsCollector._fetch_item(client, 123) is None

    def test_deleted_item_returns_none(self):
        client = MagicMock(spec=httpx.Client)
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"type": "story", "deleted": True}
        client.get.return_value = response

        assert HackerNewsCollector._fetch_item(client, 123) is None

    def test_non_story_type_returns_none(self):
        client = MagicMock(spec=httpx.Client)
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"type": "comment"}
        client.get.return_value = response

        assert HackerNewsCollector._fetch_item(client, 123) is None

    def test_non_200_returns_none(self):
        client = MagicMock(spec=httpx.Client)
        response = MagicMock()
        response.status_code = 404
        client.get.return_value = response

        assert HackerNewsCollector._fetch_item(client, 123) is None

    def test_no_url_fallback(self):
        client = MagicMock(spec=httpx.Client)
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "type": "story",
            "title": "Ask HN: Question",
        }
        client.get.return_value = response

        item = HackerNewsCollector._fetch_item(client, 456)
        assert item is not None
        assert item.url == "https://news.ycombinator.com/item?id=456"
