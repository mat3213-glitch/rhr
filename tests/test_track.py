"""Tests for pipeline/track.py — _render_body, track (dry_run), _create_issue."""
import json
from unittest.mock import MagicMock, patch

from pipeline.track import _render_body, _create_issue, track, MIN_SCORE_TO_TRACK


def _make_cand_row(**overrides):
    defaults = dict(
        id=1, title="Test Candidate", summary="A summary", category="digital_asset",
        method_type="bot", passive_level="semi_passive", est_roi_band="medium",
        risk_band="low", time_to_setup="weekend", vibe_codability_score=0.8,
        score=0.42,
    )
    defaults.update(overrides)
    row = MagicMock()
    row.__getitem__ = lambda self, key: defaults.get(key)
    return row


def _make_signal_row(**overrides):
    defaults = dict(
        url="https://example.com", title="Signal Title", source="hackernews",
        points=42, matched_groups='["money_making"]',
    )
    defaults.update(overrides)
    row = MagicMock()
    row.__getitem__ = lambda self, key: defaults.get(key)
    return row


class TestRenderBody:
    def test_contains_category(self):
        cand = _make_cand_row()
        body = _render_body(cand, [])
        assert "`digital_asset`" in body

    def test_contains_score(self):
        cand = _make_cand_row(score=0.42)
        body = _render_body(cand, [])
        assert "0.420" in body

    def test_contains_signals(self):
        cand = _make_cand_row()
        sig = _make_signal_row()
        body = _render_body(cand, [sig])
        assert "hackernews" in body
        assert "Signal Title" in body

    def test_no_signals(self):
        cand = _make_cand_row()
        body = _render_body(cand, [])
        assert "_none_" in body

    def test_no_summary(self):
        cand = _make_cand_row(summary=None)
        body = _render_body(cand, [])
        assert "no summary" in body


class TestCreateIssue:
    @patch("pipeline.track.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="https://github.com/repo/issues/42\n", returncode=0
        )
        result = _create_issue("Title", "Body", ["label1"])
        assert result == 42
        mock_run.assert_called_once()

    @patch("pipeline.track.subprocess.run")
    def test_digit_output(self, mock_run):
        mock_run.return_value = MagicMock(stdout="42\n", returncode=0)
        result = _create_issue("Title", "Body", [])
        assert result == 42

    @patch("pipeline.track.subprocess.run", side_effect=FileNotFoundError)
    def test_gh_not_found(self, mock_run):
        result = _create_issue("Title", "Body", [])
        assert result is None

    @patch("pipeline.track.subprocess.run")
    def test_gh_failure(self, mock_run):
        import subprocess
        mock_run.side_effect = subprocess.CalledProcessError(1, "gh", stderr="error")
        result = _create_issue("Title", "Body", [])
        assert result is None


class TestTrack:
    def _insert_candidate(self, db, cand_id, score=0.5):
        db.execute(
            """INSERT INTO candidates (id, title, category, method_type, passive_level,
               est_roi_band, risk_band, time_to_setup, vibe_codability_score,
               trend_velocity, score, funnel_stage)
               VALUES (?, 'Test', 'digital_asset', 'bot', 'semi_passive',
               'medium', 'low', 'weekend', 0.8, 0.5, ?, 'L2-scored')""",
            (cand_id, score),
        )
        db.commit()

    def test_dry_run(self, db):
        self._insert_candidate(db, 1, score=0.5)
        result = track(db, top_n=5, dry_run=True)
        assert result["considered"] == 1
        assert result["tracked"] == 1

    def test_excludes_low_score(self, db):
        self._insert_candidate(db, 1, score=0.01)
        result = track(db, top_n=5, dry_run=True)
        assert result["considered"] == 0

    def test_excludes_archived(self, db):
        db.execute(
            """INSERT INTO candidates (id, title, category, method_type, passive_level,
               est_roi_band, risk_band, time_to_setup, vibe_codability_score,
               trend_velocity, score, funnel_stage)
               VALUES (?, 'Test', 'digital_asset', 'bot', 'semi_passive',
               'medium', 'low', 'weekend', 0.8, 0.5, 0.5, 'archived')""",
            (1,),
        )
        db.commit()
        result = track(db, top_n=5, dry_run=True)
        assert result["considered"] == 0

    def test_excludes_already_tracked(self, db):
        self._insert_candidate(db, 1, score=0.5)
        db.execute("UPDATE candidates SET github_issue_number = 42 WHERE id = 1")
        db.commit()
        result = track(db, top_n=5, dry_run=True)
        assert result["considered"] == 0
