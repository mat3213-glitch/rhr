"""Canonical data models for RHR.

Two core entities flow through the pipeline:

* ``RawItem``   — what a collector hands back, before it touches the DB.
* ``Signal``    — the L0/L1 normalised row stored in ``signals``.

Candidates (L2) are created by the classifier from one or more Signals and are
written straight to SQLite (see pipeline/classify.py); they don't need a
dedicated pydantic model for the First Slice, only the scalar fields defined in
schema.sql.
"""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def strip_html(text: str | None) -> str | None:
    """Crude HTML → plain text: drop tags, unescape entities, collapse whitespace.

    Good enough for classification/summary; collectors that need structure
    (e.g. to extract links) do that before calling this.
    """
    if not text:
        return text
    out = _TAG_RE.sub(" ", text)
    out = html.unescape(out)
    out = _WS_RE.sub(" ", out).strip()
    return out or None


def utcnow_iso() -> str:
    """ISO8601 UTC timestamp, e.g. ``2026-06-20T11:30:00Z``."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class RawItem(BaseModel):
    """A single raw item returned by a collector, pre-DB.

    Collectors must populate at least ``source``, ``source_item_id`` and
    ``fetched_at``. Everything else is best-effort. Normalisation
    (pipeline/normalize.py) fills gaps and computes ``dedup_key``.
    """

    source: str
    source_item_id: str
    url: Optional[str] = None
    title: Optional[str] = None
    body_text: Optional[str] = None
    author: Optional[str] = None
    fetched_at: str = Field(default_factory=utcnow_iso)
    published_at: Optional[str] = None
    language: Optional[str] = None
    points: Optional[int] = None
    comments_count: Optional[int] = None
    matched_groups: list[str] = Field(default_factory=list)
    embedded_links: list[str] = Field(default_factory=list)


class Signal(RawItem):
    """A RawItem after normalisation — adds ``dedup_key``.

    Stored 1:1 in the ``signals`` table.
    """

    dedup_key: str
    l1_status: str = "new"
