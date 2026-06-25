"""Telegram channel collector — public preview via t.me/s/.

Parses the public preview pages (t.me/s/<channel>) which are available
for any public channel without authentication. No API keys needed.
"""
from __future__ import annotations

import hashlib
import re
from urllib.parse import urljoin

import httpx

from collectors.base import Collector, register
from models import RawItem, strip_html, utcnow_iso


@register
class TelegramCollector(Collector):
    type = "telegram"

    def fetch(self) -> list[RawItem]:
        channels: list[str] = self.params.get("channels", [])
        max_per = int(self.params.get("max_messages_per_channel", 50))

        items: list[RawItem] = []
        for ch in channels:
            ch = ch.lstrip("@").strip("/")
            ch_items = self._fetch_channel(ch, max_per)
            items.extend(ch_items)
        return items

    def _fetch_channel(self, channel: str, max_items: int) -> list[RawItem]:
        url = f"https://t.me/s/{channel}"
        try:
            with httpx.Client(timeout=20, follow_redirects=True) as client:
                r = client.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; RHR/1.0)"},
                )
                r.raise_for_status()
                html = r.text
        except Exception:
            return []

        return self._parse_messages(html, channel, max_items)

    def _parse_messages(self, html: str, channel: str, max_items: int) -> list[RawItem]:
        items: list[RawItem] = []

        text_blocks = re.findall(
            r'<div[^>]*class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            html,
            re.DOTALL,
        )

        date_blocks = re.findall(
            r'<time[^>]*datetime="([^"]+)"[^>]*>',
            html,
        )

        author_blocks = re.findall(
            r'<a[^>]*class="tgme_widget_message_author[^"]*"[^>]*href="([^"]*)"[^>]*>\s*<span[^>]*>([^<]+)</span>',
            html,
            re.DOTALL,
        )

        link_blocks = re.findall(
            r'data-post="([^"]+)"',
            html,
        )

        for i, text_html in enumerate(text_blocks[:max_items]):
            body = strip_html(text_html)
            if not body:
                continue

            published = None
            if i < len(date_blocks):
                published = date_blocks[i]
                if not published.endswith("Z"):
                    published += "Z"

            author = channel
            if i < len(author_blocks):
                author = author_blocks[i][1].strip()

            msg_url = None
            if i < len(link_blocks):
                msg_url = f"https://t.me/{link_blocks[i]}"

            source_id = hashlib.md5(f"{channel}:{body[:100]}".encode()).hexdigest()[:12]

            items.append(
                RawItem(
                    source="telegram",
                    source_item_id=f"telegram:{channel}:{source_id}",
                    url=msg_url,
                    body_text=body[:500] if body else None,
                    author=author,
                    fetched_at=utcnow_iso(),
                    published_at=published,
                )
            )

        return items
