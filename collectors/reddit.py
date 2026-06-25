"""Reddit collector — redlib/libreddit mirror RSS feeds.

Uses public mirror instances to fetch subreddit RSS without API keys.
Rotates mirrors if one is blocked. Filters by min_score.
"""
from __future__ import annotations

import hashlib

import feedparser
import httpx

from collectors.base import Collector, register
from models import RawItem, strip_html, utcnow_iso

DEFAULT_MIRRORS = [
    "https://redlib.catsarch.com",
    "https://l.redlib.private.coffee",
]


@register
class RedditCollector(Collector):
    type = "reddit"

    def fetch(self) -> list[RawItem]:
        mirrors = self.params.get("mirrors", DEFAULT_MIRRORS)
        subreddits = self.params.get("subreddits", [])
        max_per_sub = int(self.params.get("max_items_per_sub", 25))
        min_score = int(self.params.get("min_score", 0))

        items: list[RawItem] = []
        for sub in subreddits:
            sub_items = self._fetch_subreddit(mirrors, sub, max_per_sub, min_score)
            items.extend(sub_items)
        return items

    def _fetch_subreddit(
        self, mirrors: list[str], subreddit: str, max_items: int, min_score: int
    ) -> list[RawItem]:
        for mirror in mirrors:
            items = self._try_mirror(mirror, subreddit, max_items, min_score)
            if items is not None:
                return items
        return []

    def _try_mirror(
        self, mirror: str, subreddit: str, max_items: int, min_score: int
    ) -> list[RawItem] | None:
        rss_url = f"{mirror}/r/{subreddit}/new.rss"
        try:
            with httpx.Client(timeout=20, follow_redirects=True) as client:
                r = client.get(
                    rss_url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; RHR/1.0)"},
                )
                r.raise_for_status()
                feed_text = r.text
        except Exception:
            return None

        parsed = feedparser.parse(feed_text)
        if not parsed.entries:
            return None

        items: list[RawItem] = []
        for entry in parsed.entries[:max_items]:
            link = entry.get("link", "")
            title = entry.get("title", "")
            summary = strip_html(entry.get("summary") or entry.get("description") or "")
            guid = entry.get("id") or link or title

            score = 0
            if entry.get("score"):
                try:
                    score = int(entry["score"])
                except (TypeError, ValueError):
                    pass

            if score < min_score:
                continue

            author = entry.get("author", "")
            if author.startswith("/u/"):
                author = author[3:]

            published = None
            if entry.get("published_parsed"):
                import datetime as _dt
                try:
                    published = _dt.datetime(
                        *entry["published_parsed"][:6], tzinfo=_dt.timezone.utc
                    ).strftime("%Y-%m-%dT%H:%M:%SZ")
                except (TypeError, ValueError):
                    pass

            source_id = hashlib.md5(guid.encode()).hexdigest()[:12]
            items.append(
                RawItem(
                    source="reddit",
                    source_item_id=f"reddit:{subreddit}:{source_id}",
                    url=link,
                    title=title,
                    body_text=summary[:500] if summary else title,
                    author=author,
                    fetched_at=utcnow_iso(),
                    published_at=published,
                    points=score,
                )
            )
        return items
