"""Tests for sandbox/ package — demand_check, mvp_templates, metrics."""
import json

from sandbox.demand_check import (
    DemandCheckResult,
    _estimate_seo_score,
    _estimate_competition,
    _generate_landing,
    list_demand_checks,
    run_demand_check,
)
from sandbox.mvp_templates import (
    MVPResult,
    TEMPLATES,
    generate_mvp,
    get_template,
    list_mvps,
    list_templates,
)
from sandbox.metrics import (
    SandboxMetrics,
    collect_metrics,
    graduate_candidate,
    kill_candidate,
    set_verdict,
    update_metrics,
)


# ── demand_check ────────────────────────────────────────────────────────────

class TestEstimateSeoScore:
    def test_high_intent_keywords(self):
        score = _estimate_seo_score("How to build a SaaS tool", None)
        assert score >= 0.5

    def test_medium_intent(self):
        score = _estimate_seo_score("A new opportunity for passive income", None)
        assert 0.3 < score < 0.7

    def test_baseline(self):
        score = _estimate_seo_score("random title", None)
        assert score == 0.3

    def test_with_summary(self):
        score = _estimate_seo_score("Title", "This is a guide for building apps")
        assert score > 0.3


class TestEstimateCompetition:
    def test_crypto_high(self):
        assert _estimate_competition("crypto_defi", "low") == "high"

    def test_algo_medium(self):
        assert _estimate_competition("algo", "low") == "medium"

    def test_high_risk(self):
        assert _estimate_competition("other", "high") == "high"

    def test_medium_risk(self):
        assert _estimate_competition("other", "medium") == "medium"

    def test_low_risk(self):
        assert _estimate_competition("other", "low") == "low"


class TestGenerateLanding:
    def test_contains_title(self):
        html = _generate_landing("My Product", "A great tool", "bot")
        assert "My Product" in html

    def test_contains_summary(self):
        html = _generate_landing("Title", "Product description", "bot")
        assert "Product description" in html

    def test_contains_email_form(self):
        html = _generate_landing("Title", "Desc", "bot")
        assert "email" in html.lower()
        assert "Notify me" in html

    def test_no_summary_default(self):
        html = _generate_landing("Title", None, "bot")
        assert "bot" in html.lower()


class TestRunDemandCheck:
    def test_creates_sandbox_run(self, db):
        # Insert a candidate first
        db.execute(
            """INSERT INTO candidates (id, title, category, method_type, passive_level,
               est_roi_band, risk_band, time_to_setup, vibe_codability_score,
               trend_velocity, score, funnel_stage)
               VALUES (1, 'Test Bot', 'digital_asset', 'bot', 'semi_passive',
               'medium', 'low', 'weekend', 0.8, 0.5, 0.5, 'L2-scored')"""
        )
        db.commit()

        result = run_demand_check(db, 1)
        assert result.candidate_id == 1
        assert result.seo_score >= 0.3
        assert result.competition_level in ("low", "medium", "high")
        assert result.landing_html is not None
        assert "Test Bot" in result.landing_html

        # Verify DB state
        row = db.execute("SELECT * FROM sandbox_runs WHERE candidate_id=1").fetchone()
        assert row is not None
        assert row["stage"] == "demand_check"

        cand = db.execute("SELECT funnel_stage FROM candidates WHERE id=1").fetchone()
        assert cand["funnel_stage"] == "L3-demand-check"

    def test_invalid_candidate(self, db):
        import pytest
        with pytest.raises(ValueError, match="not found"):
            run_demand_check(db, 999)


class TestListDemandChecks:
    def test_empty(self, db):
        assert list_demand_checks(db) == []

    def test_with_data(self, db):
        db.execute(
            """INSERT INTO candidates (id, title, category, method_type, passive_level,
               est_roi_band, risk_band, time_to_setup, vibe_codability_score,
               trend_velocity, score, funnel_stage)
               VALUES (1, 'Test', 'other', 'bot', 'semi_passive',
               'medium', 'low', 'weekend', 0.8, 0.5, 0.5, 'L3-demand-check')"""
        )
        db.execute(
            "INSERT INTO sandbox_runs (candidate_id, stage, verdict) VALUES (1, 'demand_check', 'pending')"
        )
        db.commit()
        runs = list_demand_checks(db)
        assert len(runs) == 1
        assert runs[0]["candidate_id"] == 1


# ── mvp_templates ───────────────────────────────────────────────────────────

class TestGetTemplate:
    def test_known_type(self):
        t = get_template("micro_saas")
        assert t is not None
        assert t["name"] == "SaaS Landing + Waitlist"

    def test_unknown_type(self):
        assert get_template("unknown") is None


class TestListTemplates:
    def test_returns_all(self):
        templates = list_templates()
        assert "micro_saas" in templates
        assert "bot" in templates
        assert "ai_wrapper" in templates
        assert len(templates) >= 6


class TestGenerateMvp:
    def test_creates_sandbox_run(self, db):
        db.execute(
            """INSERT INTO candidates (id, title, category, method_type, passive_level,
               est_roi_band, risk_band, time_to_setup, vibe_codability_score,
               trend_velocity, score, funnel_stage)
               VALUES (1, 'Test Bot', 'digital_asset', 'bot', 'semi_passive',
               'medium', 'low', 'weekend', 0.8, 0.5, 0.5, 'L3-demand-check')"""
        )
        db.commit()

        result = generate_mvp(db, 1)
        assert result.candidate_id == 1
        assert result.template_name == "Telegram Bot"
        assert "bot.py" in result.files_generated

        row = db.execute("SELECT * FROM sandbox_runs WHERE candidate_id=1").fetchone()
        assert row["stage"] == "micro_mvp"

        cand = db.execute("SELECT funnel_stage FROM candidates WHERE id=1").fetchone()
        assert cand["funnel_stage"] == "L4-mvp"

    def test_unknown_method_falls_back(self, db):
        db.execute(
            """INSERT INTO candidates (id, title, category, method_type, passive_level,
               est_roi_band, risk_band, time_to_setup, vibe_codability_score,
               trend_velocity, score, funnel_stage)
               VALUES (1, 'Test', 'other', 'other', 'semi_passive',
               'medium', 'low', 'weekend', 0.8, 0.5, 0.5, 'L3-demand-check')"""
        )
        db.commit()
        result = generate_mvp(db, 1)
        assert result.template_name == "Generic MVP"


# ── metrics ─────────────────────────────────────────────────────────────────

class TestCollectMetrics:
    def test_empty(self, db):
        m = collect_metrics(db)
        assert m.total_runs == 0

    def test_with_data(self, db):
        db.execute(
            """INSERT INTO candidates (id, title, category, method_type, passive_level,
               est_roi_band, risk_band, time_to_setup, vibe_codability_score,
               trend_velocity, score, funnel_stage)
               VALUES (1, 'Test', 'other', 'bot', 'semi_passive',
               'medium', 'low', 'weekend', 0.8, 0.5, 0.5, 'L2-scored')"""
        )
        db.execute(
            "INSERT INTO sandbox_runs (candidate_id, stage, verdict, metrics_json) "
            "VALUES (1, 'demand_check', 'go', '{\"visits\": 100, \"signups\": 5}')"
        )
        db.execute(
            "INSERT INTO sandbox_runs (candidate_id, stage, verdict, metrics_json) "
            "VALUES (1, 'micro_mvp', 'pending', '{\"visits\": 50, \"signups\": 2}')"
        )
        db.commit()

        m = collect_metrics(db)
        assert m.total_runs == 2
        assert m.demand_checks == 1
        assert m.micro_mvps == 1
        assert m.verdicts["go"] == 1
        assert m.verdicts["pending"] == 1
        assert m.total_visits == 150
        assert m.total_signups == 7


class TestSetVerdict:
    def test_sets_verdict(self, db):
        db.execute(
            """INSERT INTO candidates (id, title, category, method_type, passive_level,
               est_roi_band, risk_band, time_to_setup, vibe_codability_score,
               trend_velocity, score, funnel_stage)
               VALUES (1, 'Test', 'other', 'bot', 'semi_passive',
               'medium', 'low', 'weekend', 0.8, 0.5, 0.5, 'L2-scored')"""
        )
        db.execute(
            "INSERT INTO sandbox_runs (candidate_id, stage, verdict) VALUES (1, 'demand_check', 'pending')"
        )
        db.commit()

        set_verdict(db, 1, "go", "Good demand signals")
        row = db.execute("SELECT verdict, verdict_reason FROM sandbox_runs WHERE id=1").fetchone()
        assert row["verdict"] == "go"
        assert row["verdict_reason"] == "Good demand signals"

    def test_invalid_verdict(self, db):
        import pytest
        with pytest.raises(ValueError, match="Invalid verdict"):
            set_verdict(db, 1, "maybe")


class TestGraduateCandidate:
    def test_graduates(self, db):
        db.execute(
            """INSERT INTO candidates (id, title, category, method_type, passive_level,
               est_roi_band, risk_band, time_to_setup, vibe_codability_score,
               trend_velocity, score, funnel_stage)
               VALUES (1, 'Test', 'other', 'bot', 'semi_passive',
               'medium', 'low', 'weekend', 0.8, 0.5, 0.5, 'L4-mvp')"""
        )
        db.commit()
        graduate_candidate(db, 1)
        cand = db.execute("SELECT funnel_stage FROM candidates WHERE id=1").fetchone()
        assert cand["funnel_stage"] == "L5-prod"
        fb = db.execute("SELECT outcome FROM scoring_feedback WHERE candidate_id=1").fetchone()
        assert fb["outcome"] == "graduated"


class TestKillCandidate:
    def test_kills(self, db):
        db.execute(
            """INSERT INTO candidates (id, title, category, method_type, passive_level,
               est_roi_band, risk_band, time_to_setup, vibe_codability_score,
               trend_velocity, score, funnel_stage)
               VALUES (1, 'Test', 'other', 'bot', 'semi_passive',
               'medium', 'low', 'weekend', 0.8, 0.5, 0.5, 'L4-mvp')"""
        )
        db.commit()
        kill_candidate(db, 1, "No demand after landing test")
        cand = db.execute("SELECT funnel_stage, archive_reason FROM candidates WHERE id=1").fetchone()
        assert cand["funnel_stage"] == "archived"
        assert cand["archive_reason"] == "No demand after landing test"
        fb = db.execute("SELECT outcome FROM scoring_feedback WHERE candidate_id=1").fetchone()
        assert fb["outcome"] == "killed_demand"


class TestUpdateMetrics:
    def test_updates_metrics(self, db):
        db.execute(
            """INSERT INTO candidates (id, title, category, method_type, passive_level,
               est_roi_band, risk_band, time_to_setup, vibe_codability_score,
               trend_velocity, score, funnel_stage)
               VALUES (1, 'Test', 'other', 'bot', 'semi_passive',
               'medium', 'low', 'weekend', 0.8, 0.5, 0.5, 'L4-mvp')"""
        )
        db.execute(
            """INSERT INTO sandbox_runs (candidate_id, stage, verdict)
               VALUES (1, 'micro_mvp', 'pending')"""
        )
        db.commit()
        update_metrics(db, 1, {"visits": 100, "signups": 5})
        row = db.execute("SELECT metrics_json FROM sandbox_runs WHERE id=1").fetchone()
        assert "100" in row["metrics_json"]


class TestListMvps:
    def test_lists_mvps(self, db):
        db.execute(
            """INSERT INTO candidates (id, title, category, method_type, passive_level,
               est_roi_band, risk_band, time_to_setup, vibe_codability_score,
               trend_velocity, score, funnel_stage)
               VALUES (1, 'Test MVP', 'other', 'bot', 'semi_passive',
               'medium', 'low', 'weekend', 0.8, 0.5, 0.5, 'L4-mvp')"""
        )
        db.execute(
            """INSERT INTO sandbox_runs (candidate_id, stage, verdict)
               VALUES (1, 'micro_mvp', 'go')"""
        )
        db.commit()
        mvps = list_mvps(db)
        assert len(mvps) == 1
        assert mvps[0]["title"] == "Test MVP"
