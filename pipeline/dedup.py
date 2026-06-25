"""Deduplication.

Two layers:
1. ``dedup_key_for`` (used at normalise time): a coarse normalised hash of the
   title/url so the exact-same story syndicated across feeds collapses to one.
2. ``dedup_signals`` (called after a scan): within the DB, mark later signals
   that share a dedup_key with an earlier one as duplicates
   (l1_status='duplicate', is_duplicate_of=canonical).
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
from urllib.parse import urlparse

from models import RawItem

_WS = re.compile(r"\s+")
_NOPUNCT = re.compile(r"[^\w\s]")


def dedup_key_for(item: RawItem) -> str:
    """Stable dedup key. Prefers a normalised URL host+path; falls back to a
    normalised title hash.

    Normalisation: lowercase, strip tracking query, strip common junk. The goal
    is "same story on two feeds → same key", not perfect identity.
    """
    key = _url_key(item.url) if item.url else None
    if not key and item.title:
        key = "t:" + _norm_text(item.title)
    if not key:
        # Last resort: the raw body hash, so we at least don't collide on None.
        body = (item.body_text or "")[:500]
        key = "b:" + hashlib.md5(body.encode()).hexdigest()
    return hashlib.md5(key.encode()).hexdigest()


def _url_key(url: str) -> str | None:
    try:
        p = urlparse(url)
    except Exception:
        return None
    if not p.netloc:
        return None
    path = p.path.rstrip("/")
    # drop trailing slug noise like /index.html
    if path.endswith("/index.html"):
        path = path[: -len("/index.html")]
    host = p.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return f"u:{host}{path}"


def _norm_text(text: str) -> str:
    t = text.lower().strip()
    t = _NOPUNCT.sub(" ", t)
    t = _WS.sub(" ", t)
    return t[:200]


def dedup_signals(conn: sqlite3.Connection) -> int:
    """Mark duplicate signals. Returns count of newly-flagged duplicates.

    Keeps the earliest-fetched signal per dedup_key as canonical.
    """
    rows = conn.execute(
        """SELECT id, dedup_key, fetched_at FROM signals
           WHERE l1_status = 'kept'
           ORDER BY dedup_key, fetched_at ASC"""
    ).fetchall()

    marked = 0
    seen: dict[str, int] = {}  # dedup_key -> canonical id
    for r in rows:
        key = r["dedup_key"]
        if key in seen:
            conn.execute(
                """UPDATE signals
                   SET l1_status = 'duplicate', is_duplicate_of = ?
                   WHERE id = ?""",
                (seen[key], r["id"]),
            )
            marked += 1
        else:
            seen[key] = r["id"]
    conn.commit()
    return marked
