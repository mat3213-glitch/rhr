"""Gumroad discover scraper — no official chart API.

Scrapes the Gumroad discover/explore pages for trending products.
Falls back to RSS if available.
"""
from __future__ import annotations

import hashlib
import re

import httpx

from collectors.base import Collector, register
from models import RawItem, strip_html, utcnow_iso

DISCOVER_URLS = [
    "https://gumroad.com/discover",
    "https://gumroad.com/discover?sort=highest_rated",
    "https://gumroad.com/discover?sort=trending",
]


@register
class GumroadCollector(Collector):
    type = "gumroad"

    def fetch(self) -> list[RawItem]:
        max_items = int(self.params.get("max_items", 30))
        items: list[RawItem] = []

        for url in DISCOVER_URLS:
            items.extend(self._scrape_page(url, max_items))

        # Deduplicate
        seen: set[str] = set()
        unique: list[RawItem] = []
        for item in items:
            if item.source_item_id not in seen:
                seen.add(item.source_item_id)
                unique.append(item)
        return unique[:max_items]

    def _scrape_page(self, url: str, max_items: int) -> list[RawItem]:
        try:
            with httpx.Client(
                timeout=20, follow_redirects=True
            ) as client:
                r = client.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; RHR/1.0)"},
                )
                r.raise_for_status()
                html = r.text
        except Exception:
            return []

        items: list[RawItem] = []

        # Extract product links — /product/<slug>
        for match in re.finditer(
            r'href="(/[^"]*?/product/[^"]+)"', html
        ):
            path = match.group(1)
            slug = path.rstrip("/").split("/")[-1]
            product_url = f"https://gumroad.com/l/{slug}"
            title = slug.replace("-", " ").title()

            items.append(
                RawItem(
                    source="gumroad",
                    source_item_id=f"gumroad:{slug}",
                    url=product_url,
                    title=title,
                    body_text=f"Gumroad product: {title}",
                    fetched_at=utcnow_iso(),
                )
            )

        # Also try data-* attributes and JSON-LD
        for match in re.finditer(
            r'"url"\s*:\s*"(https://[^"]*gumroad\.com/l/[^"]+)"', html
        ):
            product_url = match.group(1)
            slug = product_url.rstrip("/").split("/")[-1]
            title = slug.replace("-", " ").title()
            items.append(
                RawItem(
                    source="gumroad",
                    source_item_id=f"gumroad:{slug}",
                    url=product_url,
                    title=title,
                    body_text=f"Gumroad product: {title}",
                    fetched_at=utcnow_iso(),
                )
            )

        return items[:max_items]
