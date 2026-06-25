"""L3 demand-check: validate demand before committing resources.

For each candidate that passes L2 scoring, we run a lightweight demand check:

1. SEO competition scan — are people searching for this?
2. Landing page generation — minimal page with email capture
3. Metrics collection — track visits, signups, conversion

This is the "prove demand with a $0 landing page" step.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class DemandCheckResult:
    candidate_id: int
    stage: str = "demand_check"
    url: str | None = None
    seo_score: float = 0.0       # 0..1, estimated search interest
    competition_level: str = "unknown"  # low | medium | high | unknown
    landing_html: str | None = None
    metrics: dict = field(default_factory=dict)
    verdict: str = "pending"     # go | no_go | pending
    verdict_reason: str | None = None


def run_demand_check(conn: sqlite3.Connection, candidate_id: int) -> DemandCheckResult:
    """Run a demand check for a single candidate.

    Steps:
    1. Fetch candidate data
    2. Generate landing page HTML
    3. Store sandbox_runs row
    4. Return result (actual deployment happens externally)
    """
    cand = conn.execute(
        """SELECT id, title, summary, category, method_type, passive_level,
                  est_roi_band, risk_band, score
           FROM candidates WHERE id=?""",
        (candidate_id,),
    ).fetchone()

    if not cand:
        raise ValueError(f"Candidate {candidate_id} not found")

    # Estimate SEO score from title keywords
    seo_score = _estimate_seo_score(cand["title"], cand["summary"])

    # Estimate competition from category + risk
    competition = _estimate_competition(cand["category"], cand["risk_band"])

    # Generate landing page
    landing = _generate_landing(cand["title"], cand["summary"], cand["method_type"])

    result = DemandCheckResult(
        candidate_id=candidate_id,
        seo_score=seo_score,
        competition_level=competition,
        landing_html=landing,
        metrics={"visits": 0, "signups": 0, "conversion": 0.0},
    )

    # Store in DB
    conn.execute(
        """INSERT INTO sandbox_runs (candidate_id, stage, metrics_json, verdict)
           VALUES (?, 'demand_check', ?, 'pending')""",
        (candidate_id, json.dumps(result.metrics)),
    )

    # Update candidate funnel stage
    conn.execute(
        "UPDATE candidates SET funnel_stage='L3-demand-check' WHERE id=?",
        (candidate_id,),
    )
    conn.commit()

    return result


def _estimate_seo_score(title: str, summary: str | None) -> float:
    """Rough SEO interest estimate based on title keywords.

    Heuristic: more specific = more search intent.
    """
    text = f"{title} {summary or ''}".lower()

    high_intent = ["how to", "guide", "tutorial", "tool", "app", "software",
                    "alternative", "vs", "review", "best", "top"]
    medium_intent = ["idea", "opportunity", "method", "strategy", "way to"]

    score = 0.3  # baseline
    for kw in high_intent:
        if kw in text:
            score += 0.1
    for kw in medium_intent:
        if kw in text:
            score += 0.05

    return min(1.0, score)


def _estimate_competition(category: str, risk_band: str) -> str:
    """Estimate competition level from category and risk."""
    if category == "crypto_defi":
        return "high"
    if category == "algo":
        return "medium"
    if risk_band in ("very_high", "high"):
        return "high"
    if risk_band == "medium":
        return "medium"
    return "low"


def _generate_landing(title: str, summary: str | None, method_type: str) -> str:
    """Generate minimal landing page HTML with email capture."""
    desc = summary or f"A new {method_type} opportunity"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ font-family: -apple-system, system-ui, sans-serif; max-width: 600px; margin: 60px auto; padding: 20px; color: #1a1a1a; }}
  h1 {{ font-size: 28px; margin-bottom: 12px; }}
  p {{ color: #555; line-height: 1.6; margin-bottom: 24px; }}
  .cta {{ background: #2563eb; color: white; padding: 12px 24px; border: none; border-radius: 8px; font-size: 16px; cursor: pointer; }}
  .cta:hover {{ background: #1d4ed8; }}
  .email-form {{ display: flex; gap: 8px; margin-top: 16px; }}
  .email-form input {{ flex: 1; padding: 10px; border: 1px solid #ddd; border-radius: 6px; font-size: 14px; }}
  .note {{ font-size: 12px; color: #999; margin-top: 8px; }}
</style>
</head>
<body>
<h1>{title}</h1>
<p>{desc}</p>
<p><strong>Interested?</strong> Leave your email and we'll notify you when it's ready.</p>
<div class="email-form">
  <input type="email" placeholder="your@email.com" id="email">
  <button class="cta" onclick="submit()">Notify me</button>
</div>
<p class="note">No spam. Unsubscribe anytime.</p>
<script>
function submit() {{
  var e = document.getElementById('email').value;
  if (e && e.includes('@')) {{
    // In production: POST to a backend. For now, log to console.
    console.log('signup:', e);
    alert('Thanks! We\\'ll be in touch.');
  }}
}}
</script>
</body>
</html>"""


def list_demand_checks(conn: sqlite3.Connection) -> list[dict]:
    """List all demand-check sandbox runs."""
    rows = conn.execute(
        """SELECT sr.id, sr.candidate_id, sr.stage, sr.url, sr.verdict,
                  sr.verdict_reason, sr.created_at, sr.metrics_json,
                  c.title, c.score
           FROM sandbox_runs sr
           JOIN candidates c ON c.id = sr.candidate_id
           WHERE sr.stage = 'demand_check'
           ORDER BY sr.id DESC"""
    ).fetchall()
    return [dict(r) for r in rows]
