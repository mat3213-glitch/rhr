"""Tests for schedule_util — cron matching and due-source dispatch."""
from __future__ import annotations

from datetime import datetime, timezone

from schedule_util import (
    cron_matches,
    is_due,
    last_success_from_db,
    source_tier,
    sources_due,
)


class TestCronMatches:
    def test_every_30_min(self):
        expr = "*/30 * * * *"
        assert cron_matches(expr, datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc))
        assert cron_matches(expr, datetime(2026, 7, 27, 10, 30, tzinfo=timezone.utc))
        assert not cron_matches(expr, datetime(2026, 7, 27, 10, 15, tzinfo=timezone.utc))

    def test_every_4_hours_at_minute_0(self):
        expr = "0 */4 * * *"
        assert cron_matches(expr, datetime(2026, 7, 27, 0, 0, tzinfo=timezone.utc))
        assert cron_matches(expr, datetime(2026, 7, 27, 4, 0, tzinfo=timezone.utc))
        assert cron_matches(expr, datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc))
        assert not cron_matches(expr, datetime(2026, 7, 27, 5, 0, tzinfo=timezone.utc))
        assert not cron_matches(expr, datetime(2026, 7, 27, 4, 30, tzinfo=timezone.utc))

    def test_daily_at_8(self):
        expr = "0 8 * * *"
        assert cron_matches(expr, datetime(2026, 7, 27, 8, 0, tzinfo=timezone.utc))
        assert not cron_matches(expr, datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc))

    def test_comma_hours(self):
        expr = "17 7,19 * * *"
        assert cron_matches(expr, datetime(2026, 7, 27, 7, 17, tzinfo=timezone.utc))
        assert cron_matches(expr, datetime(2026, 7, 27, 19, 17, tzinfo=timezone.utc))
        assert not cron_matches(expr, datetime(2026, 7, 27, 12, 17, tzinfo=timezone.utc))


class TestIsDue:
    def test_due_when_tick_after_last_success(self):
        # last success 03:30; schedule fires at 04:00; now 04:10 → due
        assert is_due(
            "0 */4 * * *",
            now=datetime(2026, 7, 27, 4, 10, tzinfo=timezone.utc),
            last_success_at="2026-07-27T03:30:00Z",
        )

    def test_not_due_when_already_ran_after_tick(self):
        # last success 04:05 (after the 04:00 tick); now 04:25 → not due
        assert not is_due(
            "0 */4 * * *",
            now=datetime(2026, 7, 27, 4, 25, tzinfo=timezone.utc),
            last_success_at="2026-07-27T04:05:00Z",
        )

    def test_never_run_due_if_tick_in_lookback(self):
        assert is_due(
            "0 8 * * *",
            now=datetime(2026, 7, 27, 8, 10, tzinfo=timezone.utc),
            last_success_at=None,
        )

    def test_never_run_not_due_outside_lookback(self):
        # 8:00 tick is >35 min before 12:00
        assert not is_due(
            "0 8 * * *",
            now=datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc),
            last_success_at=None,
        )


class TestSourcesDue:
    CFG = {
        "hackernews": {
            "enabled": True,
            "tier": "public",
            "type": "hackernews",
            "schedule": "*/30 * * * *",
        },
        "youtube": {
            "enabled": True,
            "tier": "public",
            "type": "youtube",
            "schedule": "0 */12 * * *",
        },
        "telegram": {
            "enabled": True,
            "tier": "deep",
            "type": "telegram",
            "schedule": "17 7,19 * * *",
        },
        "disabled": {
            "enabled": False,
            "tier": "public",
            "type": "rss",
            "schedule": "*/30 * * * *",
        },
    }

    def test_public_tier_excludes_deep(self):
        now = datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc)
        names = sources_due(
            self.CFG,
            now=now,
            tier="public",
            last_success={},  # never run → lookback window
            respect_schedule=True,
        )
        assert "telegram" not in names
        assert "disabled" not in names
        assert "hackernews" in names  # */30 matches :00

    def test_youtube_not_due_midday_if_recently_ran(self):
        now = datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc)
        names = sources_due(
            self.CFG,
            now=now,
            tier="public",
            last_success={"youtube": "2026-07-27T00:05:00Z", "hackernews": "2026-07-27T09:35:00Z"},
            respect_schedule=True,
        )
        # 00:00 was the last 12h tick; already ran after it → youtube not due
        # hackernews: last at 09:35, tick at 10:00 → due
        assert "youtube" not in names
        assert "hackernews" in names

    def test_youtube_due_at_noon_tick(self):
        now = datetime(2026, 7, 27, 12, 5, tzinfo=timezone.utc)
        names = sources_due(
            self.CFG,
            now=now,
            tier="public",
            last_success={"youtube": "2026-07-27T00:05:00Z"},
            respect_schedule=True,
        )
        assert "youtube" in names

    def test_respect_schedule_false_returns_all_enabled_in_tier(self):
        names = sources_due(self.CFG, tier="public", respect_schedule=False)
        assert set(names) == {"hackernews", "youtube"}

    def test_deep_tier(self):
        names = sources_due(self.CFG, tier="deep", respect_schedule=False)
        assert names == ["telegram"]


class TestSourceTier:
    def test_default_public(self):
        assert source_tier({}) == "public"
        assert source_tier({"tier": "deep"}) == "deep"


class TestLastSuccessFromDb:
    def test_reads_run_log(self, db):
        db.execute(
            """INSERT INTO run_log(command, source, started_at, finished_at, status)
               VALUES ('scan:hackernews', 'hackernews', '2026-01-01T00:00:00Z',
                       '2026-01-01T00:01:00Z', 'ok')"""
        )
        db.execute(
            """INSERT INTO run_log(command, source, started_at, finished_at, status)
               VALUES ('scan:hackernews', 'hackernews', '2026-01-01T00:30:00Z',
                       '2026-01-01T00:31:00Z', 'ok')"""
        )
        db.execute(
            """INSERT INTO run_log(command, source, started_at, finished_at, status)
               VALUES ('scan:rss', 'rss', '2026-01-01T00:00:00Z',
                       '2026-01-01T00:00:30Z', 'error')"""
        )
        db.commit()
        last = last_success_from_db(db)
        assert last["hackernews"] == "2026-01-01T00:31:00Z"
        assert "rss" not in last
