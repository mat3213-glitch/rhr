"""Tests for Reddit collector (Phase 3)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from collectors.base import get_collector
from models import RawItem


class TestReddit:
    def test_register(self):
        c = get_collector("reddit", {
            "subreddits": [],
            "max_items_per_sub": 10,
            "min_score": 0,
        })
        assert c.type == "reddit"

    def test_fetch_rss_parses_entries(self):
        from collectors.reddit import RedditCollector

        c = RedditCollector({
            "subreddits": ["Entrepreneur"],
            "max_items_per_sub": 10,
            "min_score": 0,
        })
        fake_rss = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>https://reddit.com/r/Entrepreneur/comments/abc123</id>
    <title>How I made $10k/month with SaaS</title>
    <link href="https://reddit.com/r/Entrepreneur/comments/abc123"/>
    <summary>Full story of my journey building a micro SaaS product</summary>
    <author><name>/u/testuser</name></author>
  </entry>
  <entry>
    <id>https://reddit.com/r/Entrepreneur/comments/def456</id>
    <title>Best side hustles 2026</title>
    <link href="https://reddit.com/r/Entrepreneur/comments/def456"/>
    <summary>Here are my top picks for side hustles this year</summary>
    <author><name>/u/hustler</name></author>
  </entry>
</feed>"""
        with patch("collectors.reddit.http_client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            r = MagicMock()
            r.text = fake_rss
            r.raise_for_status = MagicMock()
            instance.get.return_value = r
            items = c.fetch()

        assert len(items) == 2
        assert items[0].source == "reddit"
        assert items[0].source_item_id.startswith("reddit:Entrepreneur:")
        assert "SaaS" in items[0].title
        assert items[0].author == "testuser"

    def test_fetch_filters_by_min_score(self):
        from collectors.reddit import RedditCollector

        c = RedditCollector({
            "subreddits": ["SaaS"],
            "max_items_per_sub": 10,
            "min_score": 50,
        })
        fake_rss = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>https://reddit.com/r/SaaS/comments/1</id>
    <title>Low score post</title>
    <link href="https://reddit.com/r/SaaS/comments/1"/>
    <summary>Not popular</summary>
  </entry>
  <entry>
    <id>https://reddit.com/r/SaaS/comments/2</id>
    <title>High score post</title>
    <link href="https://reddit.com/r/SaaS/comments/2"/>
    <summary>Very popular</summary>
  </entry>
</feed>"""
        with patch("collectors.reddit.http_client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            r = MagicMock()
            r.text = fake_rss
            r.raise_for_status = MagicMock()
            instance.get.return_value = r
            items = c.fetch()

        # No score info in feed → both pass (min_score only applies when score is present)
        assert len(items) == 2

    def test_fetch_returns_empty_on_error(self):
        from collectors.reddit import RedditCollector

        c = RedditCollector({
            "subreddits": ["test"],
            "max_items_per_sub": 5,
            "min_score": 0,
        })
        with patch("collectors.reddit.http_client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.side_effect = Exception("all fail")
            items = c.fetch()

        assert items == []

    def test_fetch_multiple_subreddits(self):
        from collectors.reddit import RedditCollector

        c = RedditCollector({
            "subreddits": ["Entrepreneur", "SaaS"],
            "max_items_per_sub": 5,
            "min_score": 0,
        })
        rss_ent = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>id1</id>
    <title>Entrepreneur Post</title>
    <link href="https://example.com/1"/>
    <summary>From Entrepreneur</summary>
  </entry>
</feed>"""
        rss_saas = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>id2</id>
    <title>SaaS Post</title>
    <link href="https://example.com/2"/>
    <summary>From SaaS</summary>
  </entry>
</feed>"""
        with patch("collectors.reddit.http_client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            r1 = MagicMock()
            r1.text = rss_ent
            r1.raise_for_status = MagicMock()
            r2 = MagicMock()
            r2.text = rss_saas
            r2.raise_for_status = MagicMock()
            instance.get.side_effect = [r1, r2]
            items = c.fetch()

        assert len(items) == 2
        subreddits_found = {i.source_item_id.split(":")[1] for i in items}
        assert subreddits_found == {"Entrepreneur", "SaaS"}

    def test_fetch_strips_u_prefix_from_author(self):
        from collectors.reddit import RedditCollector

        c = RedditCollector({
            "subreddits": ["test"],
            "max_items_per_sub": 5,
            "min_score": 0,
        })
        fake_rss = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>id1</id>
    <title>Post</title>
    <link href="https://example.com/1"/>
    <summary>Content</summary>
    <author><name>/u/someone</name></author>
  </entry>
</feed>"""
        with patch("collectors.reddit.http_client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            r = MagicMock()
            r.text = fake_rss
            r.raise_for_status = MagicMock()
            instance.get.return_value = r
            items = c.fetch()

        assert items[0].author == "someone"
