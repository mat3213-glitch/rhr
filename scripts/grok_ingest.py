#!/usr/bin/env python3
"""grok_ingest.py — конвертирует grok_*.json из signals/incoming/ → JSON lines в stdout.

Формат Grok: JSON-массив [{type, what, why_us, revenue, source_link, source_platform, score}, ...]
Формат RHR:  JSON lines {source, source_item_id, url, title, body_text, ...}

Использование:
  python scripts/grok_ingest.py | python run.py ingest-stdin
  python scripts/grok_ingest.py signals/incoming/grok_2026-07-10.json  # конкретный файл
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def file_to_items(filepath: str) -> list[dict]:
    """Read a Grok signal file and return normalized RHR items."""
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
    for entry in doc:
        url = entry.get("source_link", "")
        if not url or not url.startswith("http"):
            continue

        what = entry.get("what", "")
        why = entry.get("why_us", "")
        revenue = entry.get("revenue", "")
        platform = entry.get("source_platform", "x")
        score = entry.get("score", 0)
        entry_type = entry.get("type", "other")

        title = what[:120] if what else url[:120]
        body = what
        if why:
            body += f"\n\n{why}"
        if revenue:
            body += f"\n\nRevenue: {revenue}"

        # Dedup key from URL
        dedup = hashlib.sha256(url.encode()).hexdigest()[:16]

        items.append({
            "source": "x_via_grok",
            "source_item_id": f"grok:{dedup}",
            "url": url,
            "title": title,
            "body_text": body.strip(),
            "author": f"grok_{platform}",
            "fetched_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "published_at": None,
            "points": score if isinstance(score, (int, float)) else None,
            "comments_count": None,
        })

    return items


def main():
    incoming_dir = os.path.join(os.path.dirname(__file__), "..", "signals", "incoming")

    if len(sys.argv) > 1:
        files = sys.argv[1:]
    else:
        files = sorted(glob.glob(os.path.join(incoming_dir, "grok_*.json")))

    if not files:
        print("[grok_ingest] no grok files found", file=sys.stderr)
        return

    total = 0
    for filepath in files:
        items = file_to_items(filepath)
        for item in items:
            print(json.dumps(item, ensure_ascii=False))
        total += len(items)
        print(f"[grok_ingest] {os.path.basename(filepath)}: {len(items)} items", file=sys.stderr)

    print(f"[grok_ingest] total: {total} items from {len(files)} files", file=sys.stderr)


if __name__ == "__main__":
    main()
