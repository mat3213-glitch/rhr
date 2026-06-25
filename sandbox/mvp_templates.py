"""L4 micro-MVP: vibe-coded product templates.

For candidates that pass demand-check (L3), we generate minimal product
templates that can be deployed as micro-MVPs. The goal is to validate
willingness to pay with the smallest possible effort.

Templates:
- SaaS landing + waitlist
- Telegram bot skeleton
- API wrapper service
- Content site with ads
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field


TEMPLATES = {
    "micro_saas": {
        "name": "SaaS Landing + Waitlist",
        "description": "Landing page with feature list, pricing, and email waitlist",
        "files": ["index.html", "style.css", "app.js"],
    },
    "bot": {
        "name": "Telegram Bot",
        "description": "Python Telegram bot with command handlers",
        "files": ["bot.py", "requirements.txt", "README.md"],
    },
    "ai_wrapper": {
        "name": "AI Wrapper Service",
        "description": "Simple API wrapper around an LLM with UI",
        "files": ["app.py", "templates/index.html", "requirements.txt"],
    },
    "scraper": {
        "name": "Data Scraper Service",
        "description": "Scheduled scraper with output dashboard",
        "files": ["scraper.py", "dashboard.html", "cron.yaml"],
    },
    "content": {
        "name": "Content Site",
        "description": "Static site with articles and ad placement",
        "files": ["index.html", "article.html", "style.css"],
    },
    "automation": {
        "name": "Automation Script",
        "description": "Python script with scheduling and notifications",
        "files": ["main.py", "config.yaml", "requirements.txt"],
    },
}


@dataclass
class MVPResult:
    candidate_id: int
    stage: str = "micro_mvp"
    template_name: str = ""
    url: str | None = None
    files_generated: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    verdict: str = "pending"
    verdict_reason: str | None = None


def get_template(method_type: str) -> dict | None:
    """Get the MVP template for a given method type."""
    return TEMPLATES.get(method_type)


def list_templates() -> dict:
    """List all available MVP templates."""
    return TEMPLATES


def generate_mvp(conn: sqlite3.Connection, candidate_id: int) -> MVPResult:
    """Generate an MVP template for a candidate.

    Reads the candidate's method_type, picks the appropriate template,
    generates scaffold files, and stores a sandbox_runs row.
    """
    cand = conn.execute(
        """SELECT id, title, summary, category, method_type, passive_level,
                  est_roi_band, risk_band, score
           FROM candidates WHERE id=?""",
        (candidate_id,),
    ).fetchone()

    if not cand:
        raise ValueError(f"Candidate {candidate_id} not found")

    method = cand["method_type"] or "other"
    template = TEMPLATES.get(method)

    if not template:
        # Fallback to generic template
        template = {
            "name": "Generic MVP",
            "description": f"Generic template for {method}",
            "files": ["index.html", "README.md"],
        }

    result = MVPResult(
        candidate_id=candidate_id,
        template_name=template["name"],
        files_generated=template["files"],
        metrics={"deploys": 0, "visits": 0, "signups": 0, "revenue": 0.0},
    )

    # Store in DB
    conn.execute(
        """INSERT INTO sandbox_runs (candidate_id, stage, metrics_json, verdict)
           VALUES (?, 'micro_mvp', ?, 'pending')""",
        (candidate_id, json.dumps(result.metrics)),
    )

    # Update candidate funnel stage
    conn.execute(
        "UPDATE candidates SET funnel_stage='L4-mvp' WHERE id=?",
        (candidate_id,),
    )
    conn.commit()

    return result


def list_mvps(conn: sqlite3.Connection) -> list[dict]:
    """List all micro-MVP sandbox runs."""
    rows = conn.execute(
        """SELECT sr.id, sr.candidate_id, sr.stage, sr.url, sr.verdict,
                  sr.verdict_reason, sr.created_at, sr.metrics_json,
                  c.title, c.score, c.method_type
           FROM sandbox_runs sr
           JOIN candidates c ON c.id = sr.candidate_id
           WHERE sr.stage = 'micro_mvp'
           ORDER BY sr.id DESC"""
    ).fetchall()
    return [dict(r) for r in rows]
