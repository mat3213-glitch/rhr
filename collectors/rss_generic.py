"""Generic RSS / Atom feed collector.

Uses feedparser — handles RSS 2.0, Atom 1.0, and most malformed feeds in the
wild. No auth, no key. Great for IndieHackers, niche Substacks, blogs.
"""
from __future__ import annotations

import hashlib
from urllib.parse import urlparse

import feedparser

from collectors.base import Collector, register
from models import RawItem, strip_html, utcnow_iso


@register
class RSSCollector(Collector):
    type = "rss"

    def fetch(self) -> list[RawItem]:
        feeds: list[str] = self.params.get("feeds", [])
        max_per = int(self.params.get("max_items_per_feed", 50))
        out: list[RawItem] = []
        for url in feeds:
            out.extend(self._fetch_one(url, max_per))
        return out

    def _fetch_one(self, feed_url: str, max_per: int) -> list[RawItem]:
        # feedparser handles http itself; no httpx needed here.
        parsed = feedparser.parse(feed_url)
        site = self._site_name(parsed, feed_url)
        items: list[RawItem] = []
        for entry in parsed.entries[:max_per]:
            guid = entry.get("id") or entry.get("link") or entry.get("title")
            if not guid:
                continue
            raw_body = _entry_body(entry)
            links = _extract_links(raw_body)   # extract from raw HTML *before* stripping
            body = strip_html(raw_body)
            items.append(
                RawItem(
                    source="rss",
                    source_item_id=_stable_guid(site, guid),
                    url=entry.get("link"),
                    title=entry.get("title"),
                    body_text=body,
                    author=_entry_author(entry),
                    fetched_at=utcnow_iso(),
                    published_at=_to_iso(entry.get("published_parsed")),
                    language=parsed.feed.get("language"),
                    embedded_links=links,
                )
            )
        return items

    @staticmethod
    def _site_name(parsed, feed_url: str) -> str:
        if parsed.feed.get("title"):
            return str(parsed.feed.title)[:60]
        host = urlparse(feed_url).netloc
        return host or feed_url


# ─── helpers ─────────────────────────────────────────────────────────────────
def _entry_body(entry) -> str | None:
    for key in ("content", "summary", "description"):
        v = entry.get(key)
        if v:
            if isinstance(v, list) and v:
                return v[0].get("value")
            if isinstance(v, str):
                return v
    return None


def _entry_author(entry) -> str | None:
    a = entry.get("author")
    if a:
        return a
    a = entry.get("authors")
    if a and isinstance(a, list) and a:
        return a[0].get("name")
    return None


def _to_iso(time_tuple) -> str | None:
    if not time_tuple:
        return None
    import datetime as _dt

    try:
        return _dt.datetime(*time_tuple[:6], tzinfo=_dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    except (TypeError, ValueError):
        return None


def _stable_guid(site: str, guid: str) -> str:
    """Stable per-item id within source 'rss': md5(site + guid)."""
    return hashlib.md5(f"{site}|{guid}".encode()).hexdigest()


import re

_LINK_RE = re.compile(r'https?://[^\s<>"\')]+', re.IGNORECASE)


def _extract_links(text: str | None) -> list[str]:
    if not text:
        return []
    return list(dict.fromkeys(_LINK_RE.findall(text)))[:20]
