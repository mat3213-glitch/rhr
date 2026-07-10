"""Tests for Phase 2 collectors: defillama, producthunt, youtube, gumroad."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from collectors.base import get_collector
from models import RawItem


# ── DeFiLlama ────────────────────────────────────────────────────────────────
class TestDeFiLlama:
    def test_register(self):
        c = get_collector("defillama", {"chains": [], "min_tvl_usd": 0, "yield_min_apr": 0})
        assert c.type == "defillama"

    def test_fetch_protocols_filters(self):
        from collectors.defillama import DeFiLlamaCollector

        c = DeFiLlamaCollector({"chains": ["Ethereum"], "min_tvl_usd": 10_000_000})
        mock_chains = [
            {"name": "Ethereum", "tvl": 50_000_000_000},
            {"name": "Solana", "tvl": 8_000_000_000},
            {"name": "BSC", "tvl": 5_000_000_000},
        ]

        with patch("collectors.defillama.http_client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            r = MagicMock()
            r.json.return_value = mock_chains
            r.raise_for_status = MagicMock()
            instance.get.return_value = r

            items = c.fetch()

        # Only Ethereum passes: chain=Ethereum, TVL>10M
        assert len(items) == 1
        assert items[0].source == "defillama"
        assert "Ethereum" in items[0].title

    def test_fetch_empty_on_error(self):
        from collectors.defillama import DeFiLlamaCollector

        c = DeFiLlamaCollector({"chains": [], "min_tvl_usd": 0, "yield_min_apr": 0})
        with patch("collectors.defillama.http_client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.side_effect = Exception("timeout")
            items = c.fetch()
        assert items == []

    def test_points_formula(self):
        from collectors.defillama import DeFiLlamaCollector

        c = DeFiLlamaCollector({"chains": [], "min_tvl_usd": 0})
        mock_chains = [
            {"name": "Ethereum", "tvl": 50_000_000_000},
        ]
        with patch("collectors.defillama.http_client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            r = MagicMock()
            r.json.return_value = mock_chains
            r.raise_for_status = MagicMock()
            instance.get.return_value = r
            items = c.fetch()

        assert len(items) == 1
        assert items[0].points == 5_000_000  # 50B / 10000

    def test_all_chains_when_empty_filter(self):
        from collectors.defillama import DeFiLlamaCollector

        c = DeFiLlamaCollector({"chains": [], "min_tvl_usd": 1_000_000})
        mock_chains = [
            {"name": "Solana", "tvl": 8_000_000_000},
        ]
        with patch("collectors.defillama.http_client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            r = MagicMock()
            r.json.return_value = mock_chains
            r.raise_for_status = MagicMock()
            instance.get.return_value = r
            items = c.fetch()

        assert len(items) == 1


# ── Product Hunt ──────────────────────────────────────────────────────────────
class TestProductHunt:
    def test_register(self):
        c = get_collector("producthunt", {"max_items": 10})
        assert c.type == "producthunt"

    def test_fetch_rss(self):
        from collectors.producthunt import ProductHuntCollector

        c = ProductHuntCollector({"max_items": 5})
        fake_rss = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>tag:www.producthunt.com,2005:Post/123</id>
    <title>My Cool App</title>
    <link href="https://www.producthunt.com/posts/my-cool-app"/>
    <summary>A cool new app for productivity</summary>
  </entry>
  <entry>
    <id>tag:www.producthunt.com,2005:Post/456</id>
    <title>Another Tool</title>
    <link href="https://www.producthunt.com/posts/another-tool"/>
    <summary>Another useful tool</summary>
  </entry>
</feed>"""
        with patch("collectors.producthunt.http_client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            r = MagicMock()
            r.text = fake_rss
            r.raise_for_status = MagicMock()
            instance.get.return_value = r

            items = c.fetch()

        assert len(items) == 2
        assert items[0].source == "producthunt"
        assert "My Cool App" in items[0].title

    def test_fetch_empty_on_error(self):
        from collectors.producthunt import ProductHuntCollector

        c = ProductHuntCollector({"max_items": 5})
        with patch("collectors.producthunt.http_client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.side_effect = Exception("fail")
            items = c.fetch()
        assert items == []

    def test_fetch_gql_path(self):
        from collectors.producthunt import ProductHuntCollector

        c = ProductHuntCollector({"max_items": 10})
        gql_response = {
            "data": {
                "posts": {
                    "edges": [
                        {
                            "node": {
                                "id": "ph_gql_1",
                                "name": "GQL Product",
                                "tagline": "A product from GQL",
                                "description": "Long description",
                                "url": "https://producthunt.com/posts/gql-product",
                                "website": "https://gql-product.com",
                                "votesCount": 42,
                                "commentsCount": 7,
                                "createdAt": "2026-06-24T10:00:00Z",
                                "topics": {"edges": [{"node": {"name": "AI"}}]},
                                "makers": [{"name": "Alice"}],
                            }
                        }
                    ]
                }
            }
        }
        with patch.dict("os.environ", {"PRODUCTHUNT_API_TOKEN": "tok123"}):
            with patch("collectors.producthunt.http_client") as MockClient:
                instance = MockClient.return_value.__enter__.return_value
                r = MagicMock()
                r.json.return_value = gql_response
                r.raise_for_status = MagicMock()
                instance.post.return_value = r
                items = c.fetch()

        assert len(items) == 1
        assert items[0].source_item_id == "ph_gql_1"
        assert items[0].points == 42
        assert "Alice" in items[0].body_text

    def test_fetch_rss_fallback_on_gql_empty(self):
        from collectors.producthunt import ProductHuntCollector

        c = ProductHuntCollector({"max_items": 5})
        empty_gql = {"data": {"posts": {"edges": []}}}
        fake_rss = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>tag:producthunt.com,2005:Post/999</id>
    <title>Fallback Product</title>
    <link href="https://www.producthunt.com/posts/fallback"/>
    <summary>From RSS fallback</summary>
  </entry>
</feed>"""
        with patch.dict("os.environ", {"PRODUCTHUNT_API_TOKEN": "tok123"}):
            with patch("collectors.producthunt.http_client") as MockClient:
                instance = MockClient.return_value.__enter__.return_value
                gql_r = MagicMock()
                gql_r.json.return_value = empty_gql
                gql_r.raise_for_status = MagicMock()
                rss_r = MagicMock()
                rss_r.text = fake_rss
                rss_r.raise_for_status = MagicMock()
                # post = GQL, get = RSS
                instance.post.return_value = gql_r
                instance.get.return_value = rss_r
                items = c.fetch()

        # GQL returned empty → fallback to RSS
        assert len(items) == 1
        assert "Fallback Product" in items[0].title


# ── YouTube ───────────────────────────────────────────────────────────────────
class TestYouTube:
    def test_register(self):
        c = get_collector("youtube", {"search_terms": [], "max_results_per_term": 5})
        assert c.type == "youtube"

    def test_skip_without_key(self):
        from collectors.youtube_search import YouTubeCollector

        c = YouTubeCollector({"search_terms": ["test"], "max_results_per_term": 5})
        with patch.dict("os.environ", {}, clear=True):
            items = c.fetch()
        assert items == []

    def test_search_parses_results(self):
        from collectors.youtube_search import YouTubeCollector

        c = YouTubeCollector({"search_terms": ["ai wrapper"], "max_results_per_term": 2})
        fake_response = {
            "items": [
                {
                    "id": {"videoId": "abc123"},
                    "snippet": {
                        "title": "How to Build an AI Wrapper",
                        "description": "Tutorial on building AI wrappers",
                        "channelTitle": "TechChannel",
                        "publishedAt": "2026-06-20T12:00:00Z",
                    },
                },
                {
                    "id": {"videoId": "def456"},
                    "snippet": {
                        "title": "AI Wrapper Side Hustle",
                        "description": "Making money with AI wrappers",
                        "channelTitle": "HustleChannel",
                        "publishedAt": "2026-06-19T08:00:00Z",
                    },
                },
            ]
        }
        with patch.dict("os.environ", {"YOUTUBE_API_KEY": "fake_key"}):
            with patch("collectors.youtube_search.http_client") as MockClient:
                instance = MockClient.return_value.__enter__.return_value
                r = MagicMock()
                r.json.return_value = fake_response
                r.raise_for_status = MagicMock()
                instance.get.return_value = r
                items = c.fetch()

        assert len(items) == 2
        assert items[0].source == "youtube"
        assert items[0].source_item_id == "yt:abc123"
        assert "TechChannel" in items[0].body_text
        assert items[1].source_item_id == "yt:def456"

    def test_search_skips_items_without_video_id(self):
        from collectors.youtube_search import YouTubeCollector

        c = YouTubeCollector({"search_terms": ["test"], "max_results_per_term": 5})
        fake_response = {
            "items": [
                {"id": {"videoId": ""}, "snippet": {"title": "No ID"}},
                {"id": {}, "snippet": {"title": "No videoId key"}},
                {"id": {"videoId": "valid1"}, "snippet": {"title": "Valid", "channelTitle": "Ch", "description": "d"}},
            ]
        }
        with patch.dict("os.environ", {"YOUTUBE_API_KEY": "fake_key"}):
            with patch("collectors.youtube_search.http_client") as MockClient:
                instance = MockClient.return_value.__enter__.return_value
                r = MagicMock()
                r.json.return_value = fake_response
                r.raise_for_status = MagicMock()
                instance.get.return_value = r
                items = c.fetch()

        assert len(items) == 1
        assert items[0].source_item_id == "yt:valid1"

    def test_search_deduplicates_across_terms(self):
        from collectors.youtube_search import YouTubeCollector

        c = YouTubeCollector({"search_terms": ["term1", "term2"], "max_results_per_term": 5})
        fake_response = {
            "items": [
                {"id": {"videoId": "same1"}, "snippet": {"title": "V1", "channelTitle": "C", "description": "d"}},
            ]
        }
        with patch.dict("os.environ", {"YOUTUBE_API_KEY": "fake_key"}):
            with patch("collectors.youtube_search.http_client") as MockClient:
                instance = MockClient.return_value.__enter__.return_value
                r = MagicMock()
                r.json.return_value = fake_response
                r.raise_for_status = MagicMock()
                instance.get.return_value = r
                items = c.fetch()

        # Same video appears in both terms — should be deduplicated
        assert len(items) == 1


# ── Gumroad ───────────────────────────────────────────────────────────────────
class TestGumroad:
    def test_register(self):
        c = get_collector("gumroad", {"max_items": 10})
        assert c.type == "gumroad"

    def test_scrape_extracts_products(self):
        from collectors.gumroad import GumroadCollector

        c = GumroadCollector({"max_items": 10})
        fake_html = 'gumroad.com/l/my-ebook some other text gumroad.com/l/another-tool'
        with patch("collectors.gumroad.http_client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            r = MagicMock()
            r.text = fake_html
            r.raise_for_status = MagicMock()
            instance.get.return_value = r

            items = c.fetch()

        assert len(items) >= 1
        assert items[0].source == "gumroad"

    def test_fetch_empty_on_error(self):
        from collectors.gumroad import GumroadCollector

        c = GumroadCollector({"max_items": 10})
        with patch("collectors.gumroad.http_client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            instance.get.side_effect = Exception("fail")
            items = c.fetch()
        assert items == []

    def test_extracts_json_ld_urls(self):
        from collectors.gumroad import GumroadCollector

        c = GumroadCollector({"max_items": 10})
        html = 'some text gumroad.com/l/my-ebook more text'
        with patch("collectors.gumroad.http_client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            r = MagicMock()
            r.text = html
            r.raise_for_status = MagicMock()
            instance.get.return_value = r
            items = c.fetch()

        assert len(items) >= 1
        assert any("my-ebook" in i.source_item_id for i in items)

    def test_deduplicates_across_pages(self):
        from collectors.gumroad import GumroadCollector

        c = GumroadCollector({"max_items": 10})
        html = 'gumroad.com/l/same-product some text'
        with patch("collectors.gumroad.http_client") as MockClient:
            instance = MockClient.return_value.__enter__.return_value
            r = MagicMock()
            r.text = html
            r.raise_for_status = MagicMock()
            instance.get.return_value = r
            items = c.fetch()

        # Same product from 3 DISCOVER_URLS, but deduplicated
        assert len(items) == 1


