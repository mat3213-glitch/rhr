"""L2 scoring pass — apply scoring/model.py to every candidate missing a score.

Idempotent: only candidates where score IS NULL get scored. Re-running after a
weights.yaml edit: pass ``--rescore`` (via run.py) to wipe & recompute all.
"""
from __future__ import annotations

import sqlite3

from scoring.model import score_candidate


def score_pending(conn: sqlite3.Connection, *, rescore: bool = False) -> int:
    if rescore:
        conn.execute("UPDATE candidates SET score = NULL")

    rows = conn.execute(
        """SELECT id, passive_level, est_roi_band, risk_band, time_to_setup,
                  vibe_codability_score, trend_velocity
             FROM candidates WHERE score IS NULL"""
    ).fetchall()

    n = 0
    for r in rows:
        composite, components = score_candidate(
            passive_level=r["passive_level"],
            est_roi_band=r["est_roi_band"],
            risk_band=r["risk_band"],
            time_to_setup=r["time_to_setup"],
            vibe_codability_score=r["vibe_codability_score"],
            trend_velocity=r["trend_velocity"],
        )
        conn.execute(
            """UPDATE candidates
               SET passive_fit=?, roi_potential=?, risk=?, speed_to_setup=?,
                   score=?, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
               WHERE id=?""",
            (
                components["passive_fit"],
                components["roi_potential"],
                components["risk"],
                components["speed_to_setup"],
                composite,
                r["id"],
            ),
        )
        n += 1
    conn.commit()
    return n
