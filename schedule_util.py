"""Cron schedule helpers for source dispatch.

``config/sources.yaml`` declares a per-source ``schedule`` (5-field cron) and
``tier`` (``public`` | ``deep``). The public GH Actions scan runs every ~30 min
and calls ``sources_due(...)`` so each source fires at its own cadence.

Deep/sensitive sources (Telegram, Reddit, …) are excluded from the public
workflow; they have dedicated workflows or self-hosted runners.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

# 5-field cron: minute hour day-of-month month day-of-week
_CRON_RE = re.compile(
    r"^(\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+(\S+)$"
)

PUBLIC_TIER = "public"
DEEP_TIER = "deep"
VALID_TIERS = frozenset({PUBLIC_TIER, DEEP_TIER})

# Default lookback when a source has never been scanned successfully.
# Covers one GH Actions 30-min tick plus jitter so first deploy still respects cadence.
DEFAULT_NEVER_RUN_LOOKBACK = timedelta(minutes=35)


def parse_cron(expr: str) -> tuple[str, str, str, str, str]:
    m = _CRON_RE.match((expr or "").strip())
    if not m:
        raise ValueError(f"invalid cron schedule (need 5 fields): {expr!r}")
    return m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)


def _field_matches(field: str, value: int, *, minimum: int, maximum: int) -> bool:
    """Match one cron field against an integer value."""
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        if part == "*":
            return True
        step = 1
        base = part
        if "/" in part:
            base, step_s = part.split("/", 1)
            step = int(step_s)
            if step <= 0:
                continue
        if base == "*":
            # */N — values in [minimum, maximum] stepping from minimum
            if (value - minimum) % step == 0:
                return True
            continue
        if "-" in base:
            lo_s, hi_s = base.split("-", 1)
            lo, hi = int(lo_s), int(hi_s)
            if lo <= value <= hi and (value - lo) % step == 0:
                return True
            continue
        # single number, optionally with step (n/step is rare; treat as value==n)
        n = int(base)
        if value == n:
            return True
    return False


def cron_matches(expr: str, when: datetime) -> bool:
    """Return True if 5-field cron ``expr`` matches ``when`` (minute resolution)."""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    minute, hour, dom, month, dow = parse_cron(expr)
    # cron DOW: 0 or 7 = Sunday, 1 = Monday … 6 = Saturday
    cron_dow = (when.weekday() + 1) % 7  # Mon=1 … Sun=0
    if not _field_matches(minute, when.minute, minimum=0, maximum=59):
        return False
    if not _field_matches(hour, when.hour, minimum=0, maximum=23):
        return False
    if not _field_matches(dom, when.day, minimum=1, maximum=31):
        return False
    if not _field_matches(month, when.month, minimum=1, maximum=12):
        return False
    # Allow both 0 and 7 for Sunday in the field
    dow_ok = _field_matches(dow, cron_dow, minimum=0, maximum=7)
    if not dow_ok and cron_dow == 0:
        dow_ok = _field_matches(dow, 7, minimum=0, maximum=7)
    return dow_ok


def iter_minutes(start: datetime, end: datetime) -> Iterable[datetime]:
    """Yield each whole minute in (start, end] (exclusive start, inclusive end)."""
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    # Align to minute boundaries
    t = start.replace(second=0, microsecond=0) + timedelta(minutes=1)
    end_m = end.replace(second=0, microsecond=0)
    while t <= end_m:
        yield t
        t += timedelta(minutes=1)


def parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    s = ts.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_due(
    schedule: str,
    *,
    now: datetime | None = None,
    last_success_at: str | None = None,
    never_run_lookback: timedelta = DEFAULT_NEVER_RUN_LOOKBACK,
) -> bool:
    """Whether ``schedule`` has a tick after the last successful run up to ``now``.

    - If never run successfully: due iff any tick falls in ``[now - lookback, now]``.
    - Otherwise: due iff any tick falls in ``(last_success, now]``.
    """
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    last = parse_iso(last_success_at)
    if last is None:
        window_start = now - never_run_lookback
        # inclusive lookback window for first run
        t = window_start.replace(second=0, microsecond=0)
        end_m = now.replace(second=0, microsecond=0)
        while t <= end_m:
            if cron_matches(schedule, t):
                return True
            t += timedelta(minutes=1)
        return False

    for t in iter_minutes(last, now):
        if cron_matches(schedule, t):
            return True
    return False


def source_tier(cfg: dict[str, Any]) -> str:
    """Return tier for a source config; default public for backwards compatibility."""
    tier = (cfg.get("tier") or PUBLIC_TIER).strip().lower()
    if tier not in VALID_TIERS:
        return PUBLIC_TIER
    return tier


def sources_due(
    sources_cfg: dict[str, Any],
    *,
    now: datetime | None = None,
    tier: str | None = PUBLIC_TIER,
    last_success: dict[str, str] | None = None,
    respect_schedule: bool = True,
) -> list[str]:
    """Names of enabled sources that should run now.

    Parameters
    ----------
    sources_cfg:
        The ``sources:`` mapping from ``config/sources.yaml``.
    tier:
        If set (``public`` / ``deep``), only that tier. ``None`` or ``\"all\"`` → all tiers.
    last_success:
        Optional map source_name → ISO timestamp of last successful scan.
    respect_schedule:
        If False, return all enabled (tier-filtered) sources ignoring cron.
    """
    now = now or datetime.now(timezone.utc)
    last_success = last_success or {}
    names: list[str] = []
    want_tier = None if tier in (None, "", "all") else tier.strip().lower()

    for name, cfg in sources_cfg.items():
        if not isinstance(cfg, dict):
            continue
        if not cfg.get("enabled", False):
            continue
        if want_tier is not None and source_tier(cfg) != want_tier:
            continue
        if not respect_schedule:
            names.append(name)
            continue
        schedule = cfg.get("schedule")
        if not schedule:
            # No schedule declared → treat as always-due when selected by tier.
            names.append(name)
            continue
        try:
            if is_due(schedule, now=now, last_success_at=last_success.get(name)):
                names.append(name)
        except ValueError:
            # Bad cron — skip rather than scanning on every tick.
            continue
    return names


def last_success_from_db(conn, source_names: Iterable[str] | None = None) -> dict[str, str]:
    """Read last successful ``scan:<name>`` timestamps from ``run_log``."""
    out: dict[str, str] = {}
    if source_names is None:
        rows = conn.execute(
            """SELECT source, MAX(finished_at) AS ts
                 FROM run_log
                WHERE status = 'ok'
                  AND source IS NOT NULL
                  AND command LIKE 'scan:%'
                GROUP BY source"""
        ).fetchall()
        for r in rows:
            if r["source"] and r["ts"]:
                out[r["source"]] = r["ts"]
        return out

    for name in source_names:
        row = conn.execute(
            """SELECT MAX(finished_at) AS ts
                 FROM run_log
                WHERE status = 'ok'
                  AND (source = ? OR command = ?)""",
            (name, f"scan:{name}"),
        ).fetchone()
        if row and row["ts"]:
            out[name] = row["ts"]
    return out
