"""Telegram channel collector — public preview via t.me/s/.

Parses the public preview pages (t.me/s/<channel>) which are available
for any public channel without authentication. No API keys needed.
Uses selectolax for robust HTML parsing (avoids regex desync issues).
"""
from __future__ import annotations

import hashlib

import httpx
from selectolax.parser import HTMLParser

from collectors.base import Collector, register
from collectors.http_util import client as http_client
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
            with http_client(timeout=20) as cl:
                r = cl.get(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (compatible; RHR/1.0)"},
                )
                r.raise_for_status()
                html = r.text
        except Exception:
            return []

        return self._parse_messages(html, channel, max_items)

    def _parse_messages(self, html: str, channel: str, max_items: int) -> list[RawItem]:
        tree = HTMLParser(html)
        items: list[RawItem] = []

        for wrapper in tree.css("div.tgme_widget_message_wrap")[:max_items]:
            text_el = wrapper.css_first("div.tgme_widget_message_text")
            body = strip_html(text_el.text()) if text_el else None
            if not body:
                continue

            time_el = wrapper.css_first("time[datetime]")
            published = time_el.attributes.get("datetime") if time_el else None
            if published and not published.endswith("Z"):
                published += "Z"

            author_el = wrapper.css_first("a.tgme_widget_message_author span")
            author = author_el.text().strip() if author_el else channel

            date_link = wrapper.css_first("a.tgme_widget_message_date")
            post_id = date_link.attributes.get("data-post", "") if date_link else ""
            msg_url = f"https://t.me/{post_id}" if post_id else None

            source_id = hashlib.sha256(f"{channel}:{body[:100]}".encode()).hexdigest()[:12]

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
