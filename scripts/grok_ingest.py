#!/usr/bin/env python3
"""grok_ingest.py — конвертирует grok_*.json из signals/incoming/ → JSON lines в stdout.

Формат Grok: JSON-массив [{type, what, why_us, revenue, source_link, score}, ...]
Формат RHR:  JSON lines {source, source_item_id, url, title, body_text, ...}

Дедупликация:
  1. По URL — проверяет signals.url в базе (cross-source dedup)
  2. По source_item_id — UNIQUE constraint в БД (защита от дублей внутри grok)
  3. По normalize_url — убирает tracking params (?utm_*, ?ref=...) перед сравнением

Использование:
  python scripts/grok_ingest.py | python run.py ingest-stdin
  python scripts/grok_ingest.py signals/incoming/grok_2026-07-10.json
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse


# Tracking params to strip for dedup comparison
_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "source", "via", "fbclid", "gclid", "mc_cid", "mc_eid",
}


def normalize_url(url: str) -> str:
    """Strip tracking params and normalize URL for dedup comparison."""
    try:
        p = urlparse(url)
        qs = parse_qs(p.query, keep_blank_values=False)
        cleaned = {k: v for k, v in qs.items() if k.lower() not in _TRACKING_PARAMS}
        new_query = urlencode(cleaned, doseq=True) if cleaned else ""
        return urlunparse((p.scheme, p.netloc, p.path.rstrip("/") or "/", "", new_query, ""))
    except Exception:
        return url.rstrip("/")


def url_dedup_key(url: str) -> str:
    """Stable dedup key from normalized URL."""
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()[:16]


def load_existing_urls(db_path: str) -> set[str]:
    """Load all normalized URLs from signals table for cross-source dedup."""
    if not os.path.isfile(db_path):
        return set()
    try:
        conn = sqlite3.connect(db_path)
        rows = conn.execute("SELECT url FROM signals WHERE url IS NOT NULL").fetchall()
        conn.close()
        return {normalize_url(r[0]) for r in rows if r[0]}
    except Exception:
        return set()


def file_to_items(filepath: str, existing_urls: set[str], seen_urls: set[str]) -> list[dict]:
    """Read a Grok signal file and return normalized RHR items, skipping duplicates."""
    try:
        with open(filepath, encoding="utf-8") as f:
            doc = json.load(f)
    except Exception as e:
        print(f"[grok_ingest] skip {filepath}: {e}", file=sys.stderr)
        return []

    if isinstance(doc, dict):
        doc = doc.get("items", doc.get("results", []))
    if not isinstance(doc, list):
        return []

    items = []
    skipped = 0
    for entry in doc:
        url = entry.get("source_link", "")
        if not url or not url.startswith("http"):
            skipped += 1
            continue

        norm = normalize_url(url)

        # Cross-source dedup: skip if URL already in signals table
        if norm in existing_urls:
            skipped += 1
            continue

        # Intra-batch dedup: skip if URL already seen in this run
        if norm in seen_urls:
            skipped += 1
            continue

        seen_urls.add(norm)

        what = entry.get("what", "")
        why = entry.get("why_us", "")
        revenue = entry.get("revenue", "")
        engagement = entry.get("engagement", "")
        platform = entry.get("source_platform", "x")
        score = entry.get("score", 0)
        entry_type = entry.get("type", "other")

        title = what[:120] if what else url[:120]
        body = what
        if why:
            body += f"\n\n{why}"
        if revenue:
            body += f"\n\nRevenue: {revenue}"
        if engagement:
            body += f"\n\nEngagement: {engagement}"

        dedup_key = url_dedup_key(url)

        items.append({
            "source": "x_via_grok",
            "source_item_id": f"grok:{dedup_key}",
            "url": url,
            "title": title,
            "body_text": body.strip(),
            "author": f"grok_{platform}",
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "published_at": None,
            "points": score if isinstance(score, (int, float)) else None,
            "comments_count": None,
        })

    if skipped:
        print(f"[grok_ingest] {os.path.basename(filepath)}: skipped {skipped} duplicates", file=sys.stderr)
    return items


def main():
    incoming_dir = os.path.join(os.path.dirname(__file__), "..", "signals", "incoming")
    db_path = os.path.join(os.path.dirname(__file__), "..", "data", "rhr.db")

    if len(sys.argv) > 1:
        files = sys.argv[1:]
    else:
        files = sorted(glob.glob(os.path.join(incoming_dir, "grok_*.json")))

    if not files:
        print("[grok_ingest] no grok files found", file=sys.stderr)
        return

    existing_urls = load_existing_urls(db_path)
    seen_urls: set[str] = set()

    total = 0
    for filepath in files:
        items = file_to_items(filepath, existing_urls, seen_urls)
        for item in items:
            print(json.dumps(item, ensure_ascii=False))
        total += len(items)
        print(f"[grok_ingest] {os.path.basename(filepath)}: {len(items)} items", file=sys.stderr)

    print(f"[grok_ingest] total: {total} new items from {len(files)} files (deduped against {len(existing_urls)} existing URLs)", file=sys.stderr)


if __name__ == "__main__":
    main()
