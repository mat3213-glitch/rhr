#!/usr/bin/env python3
"""Bridge RHR -> s2c: forward top candidates to the moderation worker.

Closes the loop "scan -> classify -> score -> (this bridge) -> worker /add ->
Bot moderation -> channel". Runs in the rhr-telegram workflow right after
classify+score, so the freshest candidates (HN, YouTube, RSS, ...) reach the
moderator without any manual step.

For each selected candidate:
  1. POST /rewrite  — rewrite title+summary into a Russian channel post via
     Workers AI (same endpoint tg-graber uses).
  2. POST /add      — queue the post for moderation as id "rhr-<candidate_id>".
  3. Mark the candidate forwarded in `bridge_forwarded` (only after a
     successful /add, so failures are retried on the next run).

Config:
  S2C_WORKER_URL     (default: https://s2c-moderation-1.mat3213.workers.dev)
  S2C_WORKER_SECRET  required unless --dry-run (value of worker WORKER_SECRET)

Usage:
  python scripts/bridge_to_s2c.py                 # forward up to 3 candidates
  python scripts/bridge_to_s2c.py --limit 5
  python scripts/bridge_to_s2c.py --dry-run       # selection only, no network
  python scripts/bridge_to_s2c.py --db path/to/rhr.db
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "rhr.db"
DEFAULT_URL = "https://s2c-moderation-1.mat3213.workers.dev"

REWRITE_PROMPT = (
    "Перепиши новость для поста в Telegram-канале о заработке, micro-SaaS и AI-проектах. "
    "Русский язык, живой и конкретный тон, 3-6 коротких абзацев. Сохрани все факты, "
    "цифры и ссылки. Без заголовка, без вступлений и прощаний, без эмодзи-салюта. "
    "Если в тексте есть ссылка на видео или продукт — оставь её."
)


def _flag(name: str) -> bool:
    return name in sys.argv


def _opt(name: str, default: str) -> str:
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def post_json(worker_url: str, secret: str, path: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        worker_url.rstrip("/") + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "X-Worker-Secret": secret,
            # Cloudflare bot-fight (error 1010) blocks the default python-urllib
            # signature; a plain custom UA passes.
            "User-Agent": "rhr-bridge/1.0",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def main() -> int:
    db_path = Path(_opt("--db", str(DEFAULT_DB)))
    limit = int(_opt("--limit", "3"))
    dry = _flag("--dry-run")
    worker_url = os.environ.get("S2C_WORKER_URL", DEFAULT_URL)
    secret = os.environ.get("S2C_WORKER_SECRET", "")
    if not dry and not secret:
        print("[bridge] S2C_WORKER_SECRET is not set; use --dry-run for selection only")
        return 2

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS bridge_forwarded (
            candidate_id INTEGER PRIMARY KEY,
            s2c_draft_id TEXT NOT NULL,
            forwarded_at TEXT NOT NULL
        )
        """
    )
    rows = conn.execute(
        """
        SELECT c.id, c.title, c.summary, c.score, MIN(s.url) AS url
          FROM candidates c
          LEFT JOIN candidate_signals cs ON cs.candidate_id = c.id
          LEFT JOIN signals s ON s.id = cs.signal_id
         WHERE c.funnel_stage = 'L2-scored'
           AND c.id NOT IN (SELECT candidate_id FROM bridge_forwarded)
         GROUP BY c.id
         ORDER BY c.score DESC, c.id ASC
         LIMIT ?
        """,
        (limit,),
    ).fetchall()
    print(f"[bridge] {len(rows)} candidate(s) selected from {db_path} (limit={limit})")

    forwarded = 0
    for row in rows:
        s2c_id = f"rhr-{row['id']}"
        source_text = f"{row['title']}. {row['summary'] or ''}".strip()
        if dry:
            print(f"  [dry-run] {s2c_id} score={row['score']:.3f} {row['title'][:80]}")
            continue
        try:
            _, rewritten = post_json(worker_url, secret, "/rewrite", {
                "text": source_text[:6000],
                "prompt": REWRITE_PROMPT,
            })
            text = (rewritten.get("result") or "").strip() or source_text
            status, resp = post_json(worker_url, secret, "/add", {
                "id": s2c_id,
                "title": row["title"][:200],
                "text": text,
            })
        except urllib.error.HTTPError as e:
            print(f"  [bridge] {s2c_id}: HTTP {e.code}, will retry next run")
            continue
        except Exception as e:
            print(f"  [bridge] {s2c_id}: {e}, will retry next run")
            continue
        if status == 200 and resp.get("ok"):
            conn.execute(
                "INSERT OR REPLACE INTO bridge_forwarded VALUES (?, ?, ?)",
                (row["id"], s2c_id, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            forwarded += 1
            print(f"  [bridge] {s2c_id}: queued for moderation")
        else:
            print(f"  [bridge] {s2c_id}: /add returned {status} {resp}, will retry next run")

    print(f"[bridge] forwarded={forwarded}/{len(rows)}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
