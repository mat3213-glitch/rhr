"""Scoring model — turns classifier labels into a 0..1 composite score.

Formula (exponents in scoring/weights.yaml):

    score = passive_fit^w_passive
          * roi_potential^w_roi
          * (1 - risk)^w_risk
          * speed_to_setup^w_speed
          * vibe_codability^w_vibe
          * trend_velocity^w_trend

All components are normalised to 0..1 first (see ``_scalar``). Multiplicative
form means a single near-zero factor (e.g. very risky) can sink a candidate —
which is what we want.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

WEIGHTS_FILE = Path(__file__).resolve().parent / "weights.yaml"


@lru_cache(maxsize=None)
def _weights() -> dict:
    with WEIGHTS_FILE.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def score_candidate(
    *,
    passive_level: str,
    est_roi_band: str,
    risk_band: str,
    time_to_setup: str,
    vibe_codability_score: float,
    trend_velocity: float,
) -> tuple[float, dict]:
    """Return (composite_score 0..1, components dict for debugging/dashboard)."""
    w = _weights()
    exp = w["exponents"]

    passive_fit = _scalar("passive_level", passive_level, default=0.5)
    roi_potential = _scalar("est_roi_band", est_roi_band, default=0.4)
    risk = _scalar("risk_band", risk_band, default=0.5)
    speed = _scalar("time_to_setup", time_to_setup, default=0.4)
    vibe = _clamp(vibe_codability_score)
    velocity = _clamp(trend_velocity)

    composite = (
        passive_fit ** exp["passive_fit"]
        * roi_potential ** exp["roi_potential"]
        * (1.0 - risk) ** exp["risk"]
        * speed ** exp["speed_to_setup"]
        * vibe ** exp["vibe_codability"]
        * velocity ** exp["trend_velocity"]
    )

    components = {
        "passive_fit": round(passive_fit, 3),
        "roi_potential": round(roi_potential, 3),
        "risk": round(risk, 3),
        "speed_to_setup": round(speed, 3),
        "vibe_codability": round(vibe, 3),
        "trend_velocity": round(velocity, 3),
        "score": round(composite, 4),
    }
    return composite, components


def _scalar(map_name: str, label: str, default: float) -> float:
    table = _weights().get(map_name, {})
    if label not in table:
        return default
    return float(table[label])


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return 0.0
    return max(lo, min(hi, x))
