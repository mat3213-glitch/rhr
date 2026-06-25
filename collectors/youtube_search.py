"""YouTube Data API v3 search collector.

Requires: YOUTUBE_API_KEY env var (get from Google Cloud Console).
Searches for videos matching configured search terms, focusing on
passive income / micro SaaS / AI wrapper niches.
"""
from __future__ import annotations

import os
from urllib.parse import urlencode

import httpx

from collectors.base import Collector, register
from models import RawItem, utcnow_iso

API = "https://www.googleapis.com/youtube/v3"


@register
class YouTubeCollector(Collector):
    type = "youtube"

    def fetch(self) -> list[RawItem]:
        api_key = os.environ.get("YOUTUBE_API_KEY", "")
        if not api_key:
            print("[youtube] YOUTUBE_API_KEY not set, skipping")
            return []

        search_terms = self.params.get("search_terms", [])
        max_per = int(self.params.get("max_results_per_term", 10))
        items: list[RawItem] = []
        seen: set[str] = set()

        with httpx.Client(timeout=20) as client:
            for term in search_terms:
                vids = self._search(client, api_key, term, max_per)
                for v in vids:
                    if v.source_item_id not in seen:
                        seen.add(v.source_item_id)
                        items.append(v)
        return items

    def _search(
        self, client: httpx.Client, api_key: str, term: str, max_results: int
    ) -> list[RawItem]:
        params = {
            "part": "snippet",
            "q": term,
            "type": "video",
            "maxResults": min(max_results, 50),
            "order": "date",
            "relevanceLanguage": "en",
            "key": api_key,
        }
        try:
            r = client.get(f"{API}/search", params=params)
            r.raise_for_status()
            data = r.json()
        except Exception:
            return []

        items: list[RawItem] = []
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            vid_id = item.get("id", {}).get("videoId", "")
            if not vid_id:
                continue

            url = f"https://www.youtube.com/watch?v={vid_id}"
            title = snippet.get("title", "")
            desc = snippet.get("description", "")
            channel = snippet.get("channelTitle", "")
            published = snippet.get("publishedAt")

            items.append(
                RawItem(
                    source="youtube",
                    source_item_id=f"yt:{vid_id}",
                    url=url,
                    title=title,
                    body_text=f"{desc[:500]}. Channel: {channel}",
                    author=channel,
                    fetched_at=utcnow_iso(),
                    published_at=published,
                )
            )
        return items
