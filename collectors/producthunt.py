"""Product Hunt collector — GraphQL API (requires token) + RSS fallback.

Primary: GraphQL API with PRODUCTHUNT_API_TOKEN.
Fallback: Atom feed (may be blocked by Cloudflare).
"""
from __future__ import annotations

import hashlib
import logging
import os

import feedparser

from collectors.base import Collector, register
from collectors.http_util import client as http_client
from models import RawItem, strip_html, utcnow_iso

FEED_URL = "https://www.producthunt.com/feed"
GQL_URL = "https://api.producthunt.com/v2/api/graphql"

GQL_QUERY = """
query {
  posts(first: 30, order: RANKING, postedAfter: "%s") {
    edges {
      node {
        id
        name
        tagline
        description
        url
        votesCount
        commentsCount
        createdAt
        website
        topics { edges { node { name } } }
        makers { name }
      }
    }
  }
}
"""

logger = logging.getLogger(__name__)


@register
class ProductHuntCollector(Collector):
    type = "producthunt"

    def fetch(self) -> list[RawItem]:
        token = os.environ.get("PRODUCTHUNT_API_TOKEN", "")
        if token:
            items = self._fetch_gql(token)
            if items:
                return items

        items = self._fetch_rss()
        if not items:
            logger.warning(
                "producthunt: RSS blocked by Cloudflare and no API token set. "
                "Set PRODUCTHUNT_API_TOKEN env var for reliable access."
            )
        return items

    def _fetch_rss(self) -> list[RawItem]:
        try:
            with http_client(timeout=20) as cl:
                r = cl.get(
                    FEED_URL,
                    headers={
                        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    },
                )
                r.raise_for_status()
                feed_text = r.text
        except Exception:
            return []

        parsed = feedparser.parse(feed_text)
        items: list[RawItem] = []
        for entry in parsed.entries[:30]:
            link = entry.get("link", "")
            title = entry.get("title", "")
            summary = strip_html(entry.get("summary") or entry.get("description") or "")
            guid = entry.get("id") or link or title

            published = None
            if entry.get("published_parsed"):
                import datetime as _dt
                try:
                    published = _dt.datetime(
                        *entry["published_parsed"][:6], tzinfo=_dt.timezone.utc
                    ).strftime("%Y-%m-%dT%H:%M:%SZ")
                except (TypeError, ValueError):
                    pass

            items.append(
                RawItem(
                    source="producthunt",
                    source_item_id=f"ph:{hashlib.sha256(guid.encode()).hexdigest()[:12]}",
                    url=link,
                    title=title,
                    body_text=summary[:500] if summary else title,
                    author=entry.get("author"),
                    fetched_at=utcnow_iso(),
                    published_at=published,
                )
            )
        return items

    def _fetch_gql(self, token: str) -> list[RawItem]:
        import datetime as _dt

        since = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=7)).strftime(
            "%Y-%m-%dT00:00:00Z"
        )
        query = GQL_QUERY % since
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        try:
            with http_client(timeout=30) as cl:
                r = cl.post(GQL_URL, json={"query": query}, headers=headers)
                r.raise_for_status()
                edges = r.json().get("data", {}).get("posts", {}).get("edges", [])
        except Exception:
            return []

        items: list[RawItem] = []
        for edge in edges:
            node = edge.get("node", {})
            topics = [
                t["node"]["name"]
                for t in node.get("topics", {}).get("edges", [])
            ]
            makers = [m.get("name", "") for m in node.get("makers", [])]

            items.append(
                RawItem(
                    source="producthunt",
                    source_item_id=node.get("id", ""),
                    url=node.get("website") or node.get("url"),
                    title=node.get("name"),
                    body_text=(
                        f"{node.get('tagline', '')}. {node.get('description', '')} "
                        f"Topics: {', '.join(topics)}. Makers: {', '.join(makers[:3])}"
                    ),
                    author=makers[0] if makers else None,
                    fetched_at=utcnow_iso(),
                    published_at=node.get("createdAt"),
                    points=node.get("votesCount"),
                    comments_count=node.get("commentsCount"),
                )
            )
        return items
