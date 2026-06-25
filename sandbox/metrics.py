"""Sandbox metrics: collect, aggregate, and report experiment outcomes.

Tracks metrics across demand-check and micro-MVP stages:
- visits, signups, conversion rate, revenue
- verdict distribution (go/no_go/pending)
- funnel conversion rates
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass


@dataclass
class SandboxMetrics:
    total_runs: int = 0
    demand_checks: int = 0
    micro_mvps: int = 0
    verdicts: dict = None  # {go: n, no_go: n, pending: n}
    avg_seo_score: float = 0.0
    total_visits: int = 0
    total_signups: int = 0
    overall_conversion: float = 0.0

    def __post_init__(self):
        if self.verdicts is None:
            self.verdicts = {"go": 0, "no_go": 0, "pending": 0}


def collect_metrics(conn: sqlite3.Connection) -> SandboxMetrics:
    """Aggregate all sandbox metrics from the database."""
    metrics = SandboxMetrics()

    # Counts by stage
    for row in conn.execute(
        "SELECT stage, COUNT(*) c FROM sandbox_runs GROUP BY stage"
    ):
        if row["stage"] == "demand_check":
            metrics.demand_checks = row["c"]
        elif row["stage"] == "micro_mvp":
            metrics.micro_mvps = row["c"]
    metrics.total_runs = metrics.demand_checks + metrics.micro_mvps

    # Verdict distribution
    for row in conn.execute(
        "SELECT verdict, COUNT(*) c FROM sandbox_runs GROUP BY verdict"
    ):
        metrics.verdicts[row["verdict"]] = row["c"]

    # Aggregate metrics from metrics_json
    total_visits = 0
    total_signups = 0
    for row in conn.execute("SELECT metrics_json FROM sandbox_runs WHERE metrics_json IS NOT NULL"):
        try:
            m = json.loads(row["metrics_json"])
            total_visits += m.get("visits", 0)
            total_signups += m.get("signups", 0)
        except (json.JSONDecodeError, TypeError):
            pass

    metrics.total_visits = total_visits
    metrics.total_signups = total_signups
    if total_visits > 0:
        metrics.overall_conversion = total_signups / total_visits

    return metrics


def update_metrics(conn: sqlite3.Connection, run_id: int, metrics: dict) -> None:
    """Update metrics for a specific sandbox run."""
    conn.execute(
        "UPDATE sandbox_runs SET metrics_json=? WHERE id=?",
        (json.dumps(metrics), run_id),
    )
    conn.commit()


def set_verdict(conn: sqlite3.Connection, run_id: int, verdict: str, reason: str | None = None) -> None:
    """Set verdict for a sandbox run."""
    if verdict not in ("go", "no_go", "pending"):
        raise ValueError(f"Invalid verdict: {verdict}")
    conn.execute(
        "UPDATE sandbox_runs SET verdict=?, verdict_reason=? WHERE id=?",
        (verdict, reason, run_id),
    )
    conn.commit()


def graduate_candidate(conn: sqlite3.Connection, candidate_id: int) -> None:
    """Mark a candidate as graduated to L5-prod."""
    conn.execute(
        "UPDATE candidates SET funnel_stage='L5-prod' WHERE id=?",
        (candidate_id,),
    )
    # Record feedback
    conn.execute(
        """INSERT INTO scoring_feedback (candidate_id, outcome, note)
           VALUES (?, 'graduated', 'Passed sandbox')""",
        (candidate_id,),
    )
    conn.commit()


def kill_candidate(conn: sqlite3.Connection, candidate_id: int, reason: str) -> None:
    """Kill a candidate with a reason."""
    conn.execute(
        "UPDATE candidates SET funnel_stage='archived', archive_reason=? WHERE id=?",
        (reason, candidate_id),
    )
    # Record feedback
    outcome = "killed_demand" if "demand" in reason.lower() else "killed_mvp"
    if "manual" in reason.lower():
        outcome = "killed_manual"
    conn.execute(
        """INSERT INTO scoring_feedback (candidate_id, outcome, note)
           VALUES (?, ?, ?)""",
        (candidate_id, outcome, reason),
    )
    conn.commit()
