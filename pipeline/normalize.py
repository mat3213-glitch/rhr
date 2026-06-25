"""L0 → L1: normalise RawItems into Signals and persist.

Responsibilities:
* Combine title + body into one searchable haystack.
* Apply the L0 keyword filter (config/keywords.yaml): keep only items that
  match at least one trigger phrase. Items that match nothing are dropped here
  — they're not money-making / demand signals. This is the cheap pre-filter
  before the (costlier) LLM classifier.
* Compute a ``dedup_key`` (see dedup.py).
* Insert into ``signals`` with l1_status='kept' (or 'duplicate' — set later by
  dedup.py). Re-inserting the same (source, source_item_id) is a no-op thanks
  to the UNIQUE constraint.
"""
from __future__ import annotations

import sqlite3

from config_loader import as_json, flattened_keywords
from models import RawItem, Signal
from pipeline.dedup import dedup_key_for


def normalize_and_store(conn: sqlite3.Connection, items: list[RawItem]) -> dict:
    """Return counters: {'inserted': n, 'skipped_existing': n, 'dropped_l0': n}."""
    triggers = flattened_keywords()
    inserted = skipped = dropped = 0

    for raw in items:
        haystack = _haystack(raw)
        matched = _match_groups(haystack)

        # L0 filter: drop items that hit no trigger at all.
        if not matched:
            dropped += 1
            continue

        data = raw.model_dump()
        data["matched_groups"] = matched
        sig = Signal(
            **data,
            dedup_key=dedup_key_for(raw),
            l1_status="kept",
        )

        cur = conn.execute(
            """
            INSERT OR IGNORE INTO signals
              (source, source_item_id, url, title, body_text, author,
               fetched_at, published_at, language, points, comments_count,
               matched_groups, embedded_links, dedup_key, l1_status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                sig.source,
                sig.source_item_id,
                sig.url,
                sig.title,
                sig.body_text,
                sig.author,
                sig.fetched_at,
                sig.published_at,
                sig.language,
                sig.points,
                sig.comments_count,
                as_json(sig.matched_groups),
                as_json(sig.embedded_links),
                sig.dedup_key,
                sig.l1_status,
            ),
        )
        if cur.rowcount:
            inserted += 1
        else:
            skipped += 1

    conn.commit()
    return {"inserted": inserted, "skipped_existing": skipped, "dropped_l0": dropped}


def _haystack(item: RawItem) -> str:
    parts = [item.title or "", item.body_text or ""]
    return " ".join(parts).lower()


def _match_groups(haystack: str) -> list[str]:
    """Return the names of keyword groups that have at least one hit."""
    from config_loader import load_keywords

    hits: list[str] = []
    for group, phrases in load_keywords().items():
        if any(p.lower() in haystack for p in phrases):
            hits.append(group)
    return hits
