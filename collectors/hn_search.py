"""HN search collector — Algolia's public index, no key, no quota.

The scheduled ``hackernews`` collector only reads fixed endpoints (top/show/ask/
best), so it cannot answer a question asked right now. This one takes a query
string and returns matching stories, which is what the ``ask`` command needs.

Algolia is the search backend HN itself uses; it is public and unauthenticated,
so this stays inside the "$0 baseline runtime" rule of the project.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from collectors.base import Collector, register
from collectors.http_util import client, retry
from models import RawItem, strip_html

API = "https://hn.algolia.com/api/v1/search"
API_RECENT = "https://hn.algolia.com/api/v1/search_by_date"


@register
class HackerNewsSearchCollector(Collector):
    type = "hn_search"

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        self.queries: list[str] = params.get("queries") or []
        self.max_items: int = params.get("max_items") or 30
        self.min_points: int = params.get("min_points") or 0
        # by_date отвечает на «что говорят СЕЙЧАС», relevance — «что вообще есть».
        self.sort_by_date: bool = bool(params.get("sort_by_date"))
        self.tags: str = params.get("tags") or "story"
        self.optional_words: bool = params.get("optional_words", True)

    def fetch(self) -> list[RawItem]:
        items: list[RawItem] = []
        seen: set[str] = set()
        url = API_RECENT if self.sort_by_date else API
        with client() as http:
            for query in self.queries:
                hits = self._search(http, url, query)
                for hit in hits:
                    object_id = str(hit.get("objectID") or "")
                    if not object_id or object_id in seen:
                        continue
                    points = hit.get("points")
                    if self.min_points and (points or 0) < self.min_points:
                        continue
                    seen.add(object_id)
                    items.append(
                        RawItem(
                            source="hn_search",
                            source_item_id=object_id,
                            url=hit.get("url")
                            or f"https://news.ycombinator.com/item?id={object_id}",
                            title=hit.get("title") or hit.get("story_title"),
                            body_text=strip_html(hit.get("story_text") or hit.get("comment_text")),
                            author=hit.get("author"),
                            published_at=_iso(hit.get("created_at_i")),
                            points=points,
                            comments_count=hit.get("num_comments"),
                            matched_groups=[query],
                        )
                    )
        return items

    @retry()
    def _search(self, http, url: str, query: str) -> list[dict]:
        params = {"query": query, "tags": self.tags,
                  "hitsPerPage": min(self.max_items, 100)}
        # Algolia по умолчанию требует ВСЕ слова, поэтому живая фраза вроде
        # «downtempo music video reference» отдавала ноль хитов — выглядело как
        # «на HN про это не пишут». optionalWords разрешает пропуски и ранжирует
        # по числу совпавших слов: спрашиваем по-человечески, ответ всё равно есть.
        if self.optional_words:
            params["optionalWords"] = query
        response = http.get(url, params=params)
        response.raise_for_status()
        return response.json().get("hits") or []


def _iso(ts: int | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
