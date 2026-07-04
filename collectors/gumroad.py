"""Gumroad discover scraper — no official chart API.

Scrapes the Gumroad discover/explore pages for trending products.
"""
from __future__ import annotations

import html as _html
import re

import httpx

from collectors.base import Collector, register
from models import RawItem, utcnow_iso

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

        seen: set[str] = set()
        unique: list[RawItem] = []
        for item in items:
            if item.source_item_id not in seen:
                seen.add(item.source_item_id)
                unique.append(item)
        return unique[:max_items]

    def _scrape_page(self, url: str, max_items: int) -> list[RawItem]:
        try:
            with httpx.Client(timeout=20, follow_redirects=True) as client:
                r = client.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    },
                )
                r.raise_for_status()
                raw_html = r.text
        except Exception:
            return []

        decoded = _html.unescape(raw_html)
        items: list[RawItem] = []

        for match in re.finditer(
            r"gumroad\.com/l/([a-zA-Z0-9_-]+)", decoded
        ):
            slug = match.group(1)
            product_url = f"https://gumroad.com/l/{slug}"

            start = max(0, match.start() - 500)
            chunk = decoded[start : match.end() + 200]

            name_match = re.search(r'"name"\s*:\s*"([^"]+)"', chunk)
            title = name_match.group(1) if name_match else slug.replace("-", " ").title()

            desc_match = re.search(r'"description"\s*:\s*"([^"]{0,300})', chunk)
            description = desc_match.group(1) if desc_match else ""

            price_match = re.search(r'"price"\s*:\s*(\d+)', chunk)
            price_cents = int(price_match.group(1)) if price_match else 0
            price_str = f"${price_cents / 100:.2f}" if price_cents else "free"

            items.append(
                RawItem(
                    source="gumroad",
                    source_item_id=f"gumroad:{slug}",
                    url=product_url,
                    title=title,
                    body_text=f"Gumroad product: {title}. Price: {price_str}. {description[:300]}",
                    fetched_at=utcnow_iso(),
                    points=price_cents // 100 if price_cents else 0,
                )
            )

        return items[:max_items]
