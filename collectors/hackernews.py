"""Hacker News collector via the public Firebase API (no key, no auth).

Endpoint: https://hacker-news.firebaseio.com/v0/<list>.json  → list of ids
Item:     https://hacker-news.firebaseio.com/v0/item/<id>.json

This is the cleanest possible source for the First Slice: free, documented,
rate-limit-friendly. We pull the story lists, fetch each item, and return
RawItems. Keyword filtering happens upstream in normalize.py / pipeline, so the
collector stays dumb and just hands back raw material.
"""
from __future__ import annotations

import httpx

from collectors.base import Collector, register
from models import RawItem, strip_html, utcnow_iso

API = "https://hacker-news.firebaseio.com/v0"
# Maps our config endpoint names to the API list names.
LIST_PATHS = {
    "topstories": "topstories",
    "newstories": "newstories",
    "beststories": "beststories",
    "askstories": "askstories",
    "showstories": "showstories",
    "jobstories": "jobstories",
}
# Job stories are rarely money-making signals; default-exclude unless asked.
DEFAULT_ENDPOINTS = ["topstories", "beststories", "showstories", "askstories"]


@register
class HackerNewsCollector(Collector):
    type = "hackernews"

    def fetch(self) -> list[RawItem]:
        endpoints = self.params.get("endpoints") or DEFAULT_ENDPOINTS
        max_per = int(self.params.get("max_items_per_endpoint", 60))

        ids: list[int] = []
        seen: set[int] = set()
        with httpx.Client(timeout=20) as client:
            for ep in endpoints:
                path = LIST_PATHS.get(ep, ep)
                r = client.get(f"{API}/{path}.json")
                r.raise_for_status()
                for item_id in r.json()[:max_per]:
                    if item_id not in seen:
                        seen.add(item_id)
                        ids.append(item_id)

            items: list[RawItem] = []
            for item_id in ids:
                item = self._fetch_item(client, item_id)
                if item is not None:
                    items.append(item)
        return items

    @staticmethod
    def _fetch_item(client: httpx.Client, item_id: int) -> RawItem | None:
        r = client.get(f"{API}/item/{item_id}.json")
        if r.status_code != 200:
            return None
        d = r.json()
        if not d or d.get("type") not in ("story", "job"):
            return None
        # Skip dead/flagged items.
        if d.get("dead") or d.get("deleted"):
            return None
        url = d.get("url")
        return RawItem(
            source="hackernews",
            source_item_id=str(item_id),
            url=url or f"https://news.ycombinator.com/item?id={item_id}",
            title=d.get("title"),
            body_text=strip_html(d.get("text")),  # only present for Ask HN / text posts
            author=d.get("by"),
            fetched_at=utcnow_iso(),
            published_at=_unix_to_iso(d.get("time")),
            points=d.get("score"),
            comments_count=d.get("descendants"),
        )


def _unix_to_iso(ts: int | None) -> str | None:
    if not ts:
        return None
    import datetime as _dt

    return _dt.datetime.fromtimestamp(ts, tz=_dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
