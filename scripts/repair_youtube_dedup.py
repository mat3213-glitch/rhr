#!/usr/bin/env python3
"""One-time repair: recompute dedup keys for YouTube signals.

The old `_url_key` stripped query strings, so every youtube.com/watch URL
collapsed to the same key and all but the earliest video were flagged
`duplicate` (4654/4655 signals). This script re-keys YouTube signals with the
fixed key function, resets them to `kept`, and re-runs dedup_signals so the
DB converges to the same state a fresh scan would produce.

Usage:
    python scripts/repair_youtube_dedup.py            # data/rhr.db
    python scripts/repair_youtube_dedup.py path/to/db
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import RawItem  # noqa: E402
from pipeline.dedup import dedup_key_for, dedup_signals  # noqa: E402

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "rhr.db"


def main() -> int:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DB
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT id, url, title, body_text
          FROM signals
         WHERE source IN ('youtube', 'youtube_ytdlp')
           OR url LIKE '%youtube.com/watch%'
           OR url LIKE '%youtu.be/%'
        """
    ).fetchall()
    print(f"repairing {len(rows)} YouTube signal(s) in {db_path}")
    updated = 0
    for row in rows:
        item = RawItem(
            source=row["source"] if "source" in row.keys() else "youtube",
            source_item_id="repair",
            url=row["url"] or "",
            title=row["title"],
            body_text=row["body_text"],
        )
        key = dedup_key_for(item)
        if key != "" and key is not None:
            conn.execute(
                """
                UPDATE signals
                   SET dedup_key = ?,
                       l1_status = 'kept',
                       is_duplicate_of = NULL
                 WHERE id = ?
                """,
                (key, row["id"]),
            )
            updated += 1
    flagged = dedup_signals(conn)
    conn.commit()
    kept = conn.execute(
        "SELECT count(*) FROM signals WHERE source IN ('youtube','youtube_ytdlp') AND l1_status='kept'"
    ).fetchone()[0]
    print(f"re-keyed={updated} re-flagged_duplicates={flagged} youtube_kept_now={kept}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
