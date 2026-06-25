"""Tests for scoring/model.py — score_candidate, _scalar, _clamp."""
from scoring.model import _clamp, _scalar, score_candidate


class TestClamp:
    def test_in_range(self):
        assert _clamp(0.5) == 0.5

    def test_below_zero(self):
        assert _clamp(-0.5) == 0.0

    def test_above_one(self):
        assert _clamp(1.5) == 1.0

    def test_exactly_zero(self):
        assert _clamp(0.0) == 0.0

    def test_exactly_one(self):
        assert _clamp(1.0) == 1.0

    def test_non_numeric(self):
        assert _clamp(None) == 0.0
        assert _clamp("abc") == 0.0

    def test_custom_bounds(self):
        assert _clamp(5, lo=0, hi=10) == 5
        assert _clamp(-1, lo=0, hi=10) == 0
        assert _clamp(15, lo=0, hi=10) == 10


class TestScalar:
    def test_known_label(self):
        assert _scalar("passive_level", "hands_off", default=0.5) == 1.0
        assert _scalar("passive_level", "flip", default=0.5) == 0.3

    def test_unknown_label_returns_default(self):
        assert _scalar("passive_level", "unknown", default=0.5) == 0.5

    def test_all_roi_bands(self):
        assert _scalar("est_roi_band", "very_low", 0.0) == 0.1
        assert _scalar("est_roi_band", "low", 0.0) == 0.3
        assert _scalar("est_roi_band", "medium", 0.0) == 0.55
        assert _scalar("est_roi_band", "high", 0.0) == 0.8
        assert _scalar("est_roi_band", "very_high", 0.0) == 1.0

    def test_all_risk_bands(self):
        assert _scalar("risk_band", "very_low", 0.0) == 0.05
        assert _scalar("risk_band", "very_high", 0.0) == 0.95

    def test_all_time_bands(self):
        assert _scalar("time_to_setup", "hours", 0.0) == 1.0
        assert _scalar("time_to_setup", "month", 0.0) == 0.2


class TestScoreCandidate:
    def test_perfect_candidate(self):
        score, components = score_candidate(
            passive_level="hands_off",
            est_roi_band="very_high",
            risk_band="very_low",
            time_to_setup="hours",
            vibe_codability_score=1.0,
            trend_velocity=1.0,
        )
        # All components are 1.0 (except risk=0.05 -> 1-0.05=0.95), so score should be high
        assert score > 0.8
        assert all(k in components for k in [
            "passive_fit", "roi_potential", "risk", "speed_to_setup",
            "vibe_codability", "trend_velocity", "score"
        ])

    def test_terrible_candidate(self):
        score, components = score_candidate(
            passive_level="flip",
            est_roi_band="very_low",
            risk_band="very_high",
            time_to_setup="month",
            vibe_codability_score=0.1,
            trend_velocity=0.1,
        )
        assert score < 0.01

    def test_zero_vibe_sinks_score(self):
        score, _ = score_candidate(
            passive_level="hands_off",
            est_roi_band="very_high",
            risk_band="very_low",
            time_to_setup="hours",
            vibe_codability_score=0.0,
            trend_velocity=1.0,
        )
        assert score == 0.0

    def test_zero_velocity_sinks_score(self):
        score, _ = score_candidate(
            passive_level="hands_off",
            est_roi_band="very_high",
            risk_band="very_low",
            time_to_setup="hours",
            vibe_codability_score=1.0,
            trend_velocity=0.0,
        )
        assert score == 0.0

    def test_components_are_rounded(self):
        _, components = score_candidate(
            passive_level="semi_passive",
            est_roi_band="medium",
            risk_band="medium",
            time_to_setup="weekend",
            vibe_codability_score=0.7,
            trend_velocity=0.5,
        )
        # Components should be rounded to 3 decimal places
        for key in ["passive_fit", "roi_potential", "risk", "speed_to_setup",
                     "vibe_codability", "trend_velocity"]:
            val = components[key]
            assert val == round(val, 3)

    def test_score_is_in_0_1(self):
        score, _ = score_candidate(
            passive_level="semi_passive",
            est_roi_band="medium",
            risk_band="medium",
            time_to_setup="weekend",
            vibe_codability_score=0.7,
            trend_velocity=0.5,
        )
        assert 0.0 <= score <= 1.0

    def test_hand_calculated_value(self):
        # passive_fit=0.6, roi=0.55, risk=0.45, speed=0.65, vibe=0.85, velocity=0.3
        # exponents: 1.0, 1.2, 1.5, 0.8, 1.6, 0.9
        score, _ = score_candidate(
            passive_level="semi_passive",
            est_roi_band="medium",
            risk_band="medium",
            time_to_setup="weekend",
            vibe_codability_score=0.85,
            trend_velocity=0.3,
        )
        # Hand-calculate:
        # 0.6^1.0 * 0.55^1.2 * (1-0.45)^1.5 * 0.65^0.8 * 0.85^1.6 * 0.3^0.9
        import math
        expected = (
            0.6 ** 1.0
            * 0.55 ** 1.2
            * 0.55 ** 1.5
            * 0.65 ** 0.8
            * 0.85 ** 1.6
            * 0.3 ** 0.9
        )
        assert abs(score - expected) < 1e-6
