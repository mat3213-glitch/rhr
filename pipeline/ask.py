"""Ad-hoc search — the "поисковик в моменте" mode.

The scheduled funnel answers *"what is trending in the money rabbit holes"* on a
cron, from terms frozen in ``config/sources.yaml``. It cannot answer *"find me X,
now"* — and that is what this module adds.

Design notes:

* Sources are built on the fly from the question, not read from the registry, so
  a question never edits shared config.
* Nothing is written to the DB unless the caller asks (``store=True``): an ad-hoc
  question must not pollute the funnel it borrows collectors from.
* Ranking is relevance + freshness + engagement, deliberately *not* the L2 money
  score — a reference hunt and a product hunt want different things on top.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from collectors.base import CollectorError, get_collector
from models import RawItem

# Каждый источник умеет искать по строке запроса. Коллекторы, которые ходят по
# фиксированной ленте (rss, defillama, gumroad), сюда не годятся — им нечего спросить.
SEARCHABLE: dict[str, dict[str, Any]] = {
    "hn": {"type": "hn_search", "params": lambda q, n, recent: {
        "queries": [q], "max_items": n, "sort_by_date": recent}},
    "youtube": {"type": "youtube_ytdlp", "params": lambda q, n, recent: {
        "search_terms": [q], "max_results_per_term": min(n, 25), "timeout": 120}},
}
DEFAULT_SOURCES = ["hn", "youtube"]
_WORD_RE = re.compile(r"[\w']+", re.UNICODE)


@dataclass
class AskResult:
    items: list[RawItem] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    per_source: dict[str, int] = field(default_factory=dict)


def _tokens(text: str | None) -> set[str]:
    return {w.lower() for w in _WORD_RE.findall(text or "") if len(w) > 2}


def _age_days(published_at: str | None) -> float | None:
    if not published_at:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(published_at, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400)
    return None


def score_item(item: RawItem, query: str) -> float:
    """Релевантность + свежесть + вовлечённость. Веса намеренно грубые: задача —
    поднять наверх очевидно подходящее, а не построить ранжирующую модель."""
    q = _tokens(query)
    hay = _tokens(item.title) | _tokens(item.body_text)
    overlap = len(q & hay) / len(q) if q else 0.0

    age = _age_days(item.published_at)
    freshness = 1.0 if age is None else 1.0 / (1.0 + age / 30.0)

    engagement = math.log1p((item.points or 0) + (item.comments_count or 0)) / 6.0
    return 3.0 * overlap + 1.5 * freshness + min(engagement, 1.5)


def ask(query: str, sources: list[str] | None = None, limit: int = 20,
        recent: bool = False, per_source: int = 30) -> AskResult:
    """Спросить у поисковых источников и вернуть ранжированный ответ."""
    result = AskResult()
    seen: set[str] = set()
    for name in (sources or DEFAULT_SOURCES):
        spec = SEARCHABLE.get(name)
        if not spec:
            result.errors[name] = f"источник не умеет искать; доступны: {sorted(SEARCHABLE)}"
            continue
        try:
            coll = get_collector(spec["type"], spec["params"](query, per_source, recent))
            items = coll.fetch()
        except (CollectorError, Exception) as exc:   # коллектор не должен ронять ответ целиком
            result.errors[name] = f"{type(exc).__name__}: {exc}"
            continue
        kept = 0
        for it in items:
            key = (it.url or "").split("?")[0] or f"{it.source}:{it.source_item_id}"
            if key in seen:
                continue
            seen.add(key)
            result.items.append(it)
            kept += 1
        result.per_source[name] = kept

    result.items.sort(key=lambda it: score_item(it, query), reverse=True)
    result.items = result.items[:limit]
    return result


def render(result: AskResult, query: str) -> str:
    """Ответ человеку: без таблиц-простыней, сразу ссылки и чем они интересны."""
    lines = [f"# Ответ на: {query}", ""]
    if result.errors:
        for name, err in result.errors.items():
            lines.append(f"- ⚠️ {name}: {err}")
        lines.append("")
    if not result.items:
        lines.append("Ничего не нашлось.")
        return "\n".join(lines)
    got = ", ".join(f"{k}={v}" for k, v in result.per_source.items())
    lines.append(f"Источники: {got}. Показано {len(result.items)}.")
    lines.append("")
    for i, it in enumerate(result.items, 1):
        meta = []
        if it.points:
            meta.append(f"{it.points}↑")
        if it.comments_count:
            meta.append(f"{it.comments_count}💬")
        if it.published_at:
            meta.append(it.published_at[:10])
        tail = f"  ({', '.join(meta)})" if meta else ""
        lines.append(f"{i}. **{(it.title or '(без заголовка)')[:110]}**{tail}")
        lines.append(f"   {it.url}")
    return "\n".join(lines)
