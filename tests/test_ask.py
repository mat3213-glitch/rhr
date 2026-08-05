"""Tests for the ad-hoc `ask` mode (поисковик в моменте)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from models import RawItem
from pipeline import ask as ask_mod


def _item(**kw) -> RawItem:
    base = dict(source="hn_search", source_item_id="1", url="https://example.com/a",
                title="AI music video pipeline", points=10, comments_count=2)
    base.update(kw)
    return RawItem(**base)


class TestScoring:
    def test_query_overlap_beats_engagement(self):
        on_topic = _item(source_item_id="1", title="downtempo music video reference",
                         points=1, comments_count=0)
        off_topic = _item(source_item_id="2", title="kubernetes operator patterns",
                          points=5000, comments_count=900)
        q = "downtempo music video reference"
        assert ask_mod.score_item(on_topic, q) > ask_mod.score_item(off_topic, q)

    def test_fresher_item_wins_when_relevance_equal(self):
        now = datetime.now(timezone.utc)
        fresh = _item(source_item_id="1",
                      published_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"))
        old = _item(source_item_id="2",
                    published_at=(now - timedelta(days=900)).strftime("%Y-%m-%dT%H:%M:%SZ"))
        q = "AI music video pipeline"
        assert ask_mod.score_item(fresh, q) > ask_mod.score_item(old, q)

    def test_unparseable_date_does_not_crash(self):
        assert ask_mod.score_item(_item(published_at="who knows"), "music") >= 0


class TestAsk:
    def test_dedups_by_url_across_sources(self, monkeypatch):
        same = "https://example.com/dup?utm=1"

        class FakeCollector:
            def __init__(self, *a, **kw):
                pass

            def fetch(self):
                return [_item(source_item_id="a", url=same),
                        _item(source_item_id="b", url=same)]

        monkeypatch.setattr(ask_mod, "get_collector", lambda t, p: FakeCollector())
        res = ask_mod.ask("music", sources=["hn", "youtube"])
        assert len(res.items) == 1

    def test_failing_source_does_not_kill_the_answer(self, monkeypatch):
        class Boom:
            def __init__(self, *a, **kw):
                pass

            def fetch(self):
                raise RuntimeError("provider down")

        class Fine:
            def __init__(self, *a, **kw):
                pass

            def fetch(self):
                return [_item()]

        calls = {"n": 0}

        def factory(type_name, params):
            calls["n"] += 1
            return Boom() if calls["n"] == 1 else Fine()

        monkeypatch.setattr(ask_mod, "get_collector", factory)
        res = ask_mod.ask("music", sources=["hn", "youtube"])
        assert len(res.items) == 1
        assert "hn" in res.errors and "provider down" in res.errors["hn"]

    def test_unknown_source_is_reported_not_raised(self):
        res = ask_mod.ask("music", sources=["mars"])
        assert "mars" in res.errors
        assert res.items == []


class TestRender:
    def test_render_lists_links_and_errors(self):
        res = ask_mod.AskResult(items=[_item()], errors={"youtube": "yt-dlp missing"},
                                per_source={"hn": 1})
        text = ask_mod.render(res, "music video")
        assert "https://example.com/a" in text
        assert "yt-dlp missing" in text

    def test_render_handles_empty_result(self):
        assert "Ничего не нашлось" in ask_mod.render(ask_mod.AskResult(), "music")


class TestHnSearchCollector:
    def test_parses_hits_and_filters_by_points(self, monkeypatch):
        from collectors.hn_search import HackerNewsSearchCollector

        hits = [
            {"objectID": "1", "title": "loud", "points": 100, "num_comments": 5,
             "url": "https://a", "created_at_i": 1700000000, "author": "x"},
            {"objectID": "2", "title": "quiet", "points": 1, "url": "https://b"},
        ]
        coll = HackerNewsSearchCollector({"queries": ["q"], "min_points": 10})
        monkeypatch.setattr(coll, "_search", lambda *a, **kw: hits)
        items = coll.fetch()
        assert [i.source_item_id for i in items] == ["1"]
        assert items[0].published_at.startswith("2023-")

    def test_missing_url_falls_back_to_hn_permalink(self, monkeypatch):
        from collectors.hn_search import HackerNewsSearchCollector

        coll = HackerNewsSearchCollector({"queries": ["q"]})
        monkeypatch.setattr(coll, "_search",
                            lambda *a, **kw: [{"objectID": "42", "title": "ask hn"}])
        assert "item?id=42" in coll.fetch()[0].url
