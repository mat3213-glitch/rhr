"""Tests for pipeline/score.py — score_pending."""
from pipeline.score import score_pending


def _insert_candidate(db, cand_id, score=None):
    db.execute(
        """INSERT INTO candidates (id, title, category, method_type, passive_level,
           est_roi_band, risk_band, time_to_setup, vibe_codability_score,
           trend_velocity, score, funnel_stage)
           VALUES (?, 'Test', 'digital_asset', 'bot', 'semi_passive',
           'medium', 'low', 'weekend', 0.8, 0.5, ?, 'L2-scored')""",
        (cand_id, score),
    )
    db.commit()


class TestScorePending:
    def test_scores_unscored_candidates(self, db):
        _insert_candidate(db, 1, score=None)
        n = score_pending(db)
        assert n == 1
        row = db.execute("SELECT score FROM candidates WHERE id=1").fetchone()
        assert row["score"] is not None
        assert 0.0 < row["score"] < 1.0

    def test_skips_already_scored(self, db):
        _insert_candidate(db, 1, score=0.5)
        n = score_pending(db)
        assert n == 0

    def test_rescore_clears_existing(self, db):
        _insert_candidate(db, 1, score=0.5)
        n = score_pending(db, rescore=True)
        assert n == 1
        row = db.execute("SELECT score FROM candidates WHERE id=1").fetchone()
        assert row["score"] is not None

    def test_returns_zero_for_empty(self, db):
        assert score_pending(db) == 0

    def test_populates_component_columns(self, db):
        _insert_candidate(db, 1, score=None)
        score_pending(db)
        row = db.execute(
            "SELECT passive_fit, roi_potential, risk, speed_to_setup FROM candidates WHERE id=1"
        ).fetchone()
        assert row["passive_fit"] is not None
        assert row["roi_potential"] is not None
        assert row["risk"] is not None
        assert row["speed_to_setup"] is not None
