"""YouTube search collector using yt-dlp instead of the YouTube Data API v3.

This module provides a key-free alternative to youtube_search.py, useful when
the Google quota (10,000 units/day) is exhausted or unavailable. It shells out
to the yt-dlp binary to perform searches and extract video metadata.

Verified on a US runner 2026-08-03: search works without any key or cookie,
while *subtitle* download does not ("Sign in to confirm you're not a bot").
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timezone
from typing import Any

from collectors.base import Collector, register
from models import RawItem


@register
class YouTubeYtDlpCollector(Collector):
    type = "youtube_ytdlp"

    def __init__(self, params: dict[str, Any]) -> None:
        super().__init__(params)
        self.search_terms: list[str] = params.get("search_terms") or []
        self.max_results_per_term: int = params.get("max_results_per_term") or 10
        self.binary: str = params.get("binary") or "yt-dlp"
        self.timeout: int = params.get("timeout") or 120
        self.upload_date_after: str | None = params.get("upload_date_after")

    def fetch(self) -> list[RawItem]:
        if not shutil.which(self.binary):
            print(
                f"[youtube_ytdlp] Binary '{self.binary}' not found. Hint: pip install yt-dlp"
            )
            return []

        items: list[RawItem] = []
        seen_ids: set[str] = set()

        for term in self.search_terms:
            try:
                cmd = [
                    self.binary,
                    "--flat-playlist",
                    "--dump-json",
                    "--no-warnings",
                    "--ignore-errors",
                    f"ytsearch{self.max_results_per_term}:{term}",
                ]
                if self.upload_date_after:
                    cmd.extend(["--dateafter", self.upload_date_after])

                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout,
                    check=False,
                )

                # yt-dlp банят по IP молча: rc!=0 + пустой stdout. Без этой строки
                # коллектор вернул бы пустой список и выглядел бы «просто ничего не нашёл».
                if proc.returncode != 0 and not proc.stdout.strip():
                    err = (proc.stderr or "").strip().splitlines()
                    print(
                        f"[youtube_ytdlp] rc={proc.returncode} for term '{term}': "
                        f"{err[-1][:200] if err else 'no stderr'}"
                    )

                collected = 0
                for line in proc.stdout.splitlines():
                    if collected >= self.max_results_per_term:
                        break
                    try:
                        entry: dict[str, Any] = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    video_id = entry.get("id")
                    if not video_id or video_id in seen_ids:
                        continue

                    raw_url = entry.get("url", "")
                    if isinstance(raw_url, str) and raw_url.startswith("http"):
                        url = raw_url
                    else:
                        url = f"https://www.youtube.com/watch?v={video_id}"

                    ts = entry.get("timestamp")
                    published_at: str | None = None
                    if isinstance(ts, int):
                        published_at = (
                            datetime.fromtimestamp(ts, tz=timezone.utc)
                            .isoformat()
                            .replace("+00:00", "Z")
                        )

                    items.append(
                        RawItem(
                            source="youtube_ytdlp",
                            source_item_id=video_id,
                            url=url,
                            title=entry.get("title"),
                            body_text=entry.get("description"),
                            author=entry.get("uploader") or entry.get("channel"),
                            points=entry.get("view_count"),
                            comments_count=entry.get("comment_count"),
                            published_at=published_at,
                            language=None,
                            matched_groups=[term],
                            embedded_links=[],
                        )
                    )
                    seen_ids.add(video_id)
                    collected += 1

            except subprocess.TimeoutExpired:
                print(f"[youtube_ytdlp] Timeout expired for term: {term}")
            except FileNotFoundError:
                print(
                    f"[youtube_ytdlp] Binary '{self.binary}' not found. Hint: pip install yt-dlp"
                )
            except OSError as exc:
                print(f"[youtube_ytdlp] OS error for term '{term}': {exc}")
            except Exception as exc:
                print(f"[youtube_ytdlp] Unexpected error for term '{term}': {exc}")

        return items
