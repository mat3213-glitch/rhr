"""Deduplication.

Two layers:
1. ``dedup_key_for`` (used at normalise time): a coarse normalised hash of the
   title/url so the exact-same story syndicated across feeds collapses to one.
2. ``dedup_signals`` (called after a scan): within the DB, mark later signals
   that share a dedup_key with an earlier one as duplicates
   (l1_status='duplicate', is_duplicate_of=canonical).

Canonical selection is stable: minimum ``(fetched_at, id)`` among kept rows
sharing a dedup_key. Ties on the same second still collapse to one survivor.
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
        key = "b:" + hashlib.sha256(body.encode()).hexdigest()[:16]
    return hashlib.sha256(key.encode()).hexdigest()[:16]


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

    Keeps the earliest signal per dedup_key as canonical, breaking ties by
    lowest ``id`` so two rows with the same second-resolution ``fetched_at``
    still collapse to exactly one ``kept`` row.
    """
    # A kept row is a duplicate iff another kept row with the same key is
    # strictly earlier by (fetched_at, id). The survivor is min(fetched_at, id).
    cur = conn.execute(
        """UPDATE signals
              SET l1_status = 'duplicate',
                  is_duplicate_of = (
                    SELECT s2.id FROM signals s2
                     WHERE s2.dedup_key = signals.dedup_key
                       AND s2.l1_status = 'kept'
                     ORDER BY s2.fetched_at ASC, s2.id ASC
                     LIMIT 1
                  )
            WHERE l1_status = 'kept'
              AND EXISTS (
                SELECT 1 FROM signals s2
                 WHERE s2.dedup_key = signals.dedup_key
                   AND s2.l1_status = 'kept'
                   AND (
                     s2.fetched_at < signals.fetched_at
                     OR (s2.fetched_at = signals.fetched_at AND s2.id < signals.id)
                   )
              )"""
    )
    # Callers (scan/pipeline) own the outer transaction; mirror prior behaviour
    # and rely on subsequent log_run/pipeline commits. Explicit commit here would
    # be fine too, but tests often assert mid-transaction state.
    return cur.rowcount
