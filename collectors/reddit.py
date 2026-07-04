"""Reddit collector — old.reddit.com RSS feeds.

Uses old.reddit.com Atom feeds (no API key needed).
Rate-limited with delays between requests to avoid 429s.
"""
from __future__ import annotations

import hashlib
import time

import feedparser
import httpx

from collectors.base import Collector, register
from models import RawItem, strip_html, utcnow_iso

REDDIT_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


@register
class RedditCollector(Collector):
    type = "reddit"

    def fetch(self) -> list[RawItem]:
        subreddits = self.params.get("subreddits", [])
        max_per_sub = int(self.params.get("max_items_per_sub", 25))
        min_score = int(self.params.get("min_score", 0))

        items: list[RawItem] = []
        for i, sub in enumerate(subreddits):
            if i > 0:
                time.sleep(2)
            sub_items = self._fetch_subreddit(sub, max_per_sub, min_score)
            items.extend(sub_items)
        return items

    def _fetch_subreddit(
        self, subreddit: str, max_items: int, min_score: int
    ) -> list[RawItem]:
        rss_url = f"https://old.reddit.com/r/{subreddit}/new/.rss"
        try:
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                r = client.get(rss_url, headers={"User-Agent": REDDIT_UA})
                r.raise_for_status()
                feed_text = r.text
        except Exception:
            return []

        parsed = feedparser.parse(feed_text)
        if not parsed.entries:
            return []

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

            if entry.get("score") is not None and score < min_score:
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
