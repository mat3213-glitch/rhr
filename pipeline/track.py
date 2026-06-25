"""Create GitHub Issues for the top-scored candidates that don't have one yet.

Uses the `gh` CLI (must be installed and authenticated in the environment).
In GitHub Actions, the default GITHUB_TOKEN already grants issue creation in
the running repo. Locally, run `gh auth login` once.

Design:
* picks the top-N candidates (by score) with no github_issue_number
* renders an issue body from the candidate + its source signals
* creates the issue and stores the issue number back on the candidate
* --dry-run prints what would be created without calling gh
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys

DEFAULT_TOP_N = 5
MIN_SCORE_TO_TRACK = 0.001   # show all scored candidates for now


def track(conn: sqlite3.Connection, *, top_n: int = DEFAULT_TOP_N, dry_run: bool = False) -> dict:
    rows = conn.execute(
        """SELECT c.id, c.title, c.summary, c.category, c.method_type,
                  c.passive_level, c.est_roi_band, c.risk_band, c.time_to_setup,
                  c.vibe_codability_score, c.score
             FROM candidates c
            WHERE c.github_issue_number IS NULL
              AND c.score IS NOT NULL
              AND c.score >= ?
              AND c.funnel_stage != 'archived'
            ORDER BY c.score DESC
            LIMIT ?""",
        (MIN_SCORE_TO_TRACK, top_n),
    ).fetchall()

    created = 0
    for r in rows:
        signals = _source_signals(conn, r["id"])
        title = f"[CANDIDATE] {r['title']}"
        body = _render_body(r, signals)
        if dry_run:
            print(f"\n--- DRY RUN: would create issue for candidate #{r['id']} "
                  f"(score {r['score']:.3f}) ---")
            print(f"TITLE: {title}")
            print(body)
            created += 1
            continue
        issue_number = _create_issue(title, body, labels=["L2-scored"])
        if issue_number:
            conn.execute(
                """UPDATE candidates
                   SET github_issue_number=?, updated_at=strftime('%Y-%m-%dT%H:%M:%SZ','now')
                   WHERE id=?""",
                (issue_number, r["id"]),
            )
            created += 1
    conn.commit()
    return {"tracked": created, "considered": len(rows)}


def _source_signals(conn: sqlite3.Connection, candidate_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT s.url, s.title, s.source, s.points, s.matched_groups
             FROM candidate_signals cs
             JOIN signals s ON s.id = cs.signal_id
            WHERE cs.candidate_id=?""",
        (candidate_id,),
    ).fetchall()


def _render_body(cand: sqlite3.Row, signals: list[sqlite3.Row]) -> str:
    sig_lines = []
    for s in signals:
        groups = json.loads(s["matched_groups"]) if s["matched_groups"] else []
        pts = f" · {s['points']}pts" if s["points"] else ""
        url = s["url"] or ""
        sig_lines.append(f"- [{s['source']}{pts}] {s['title']} {url} _(groups: {', '.join(groups) or '—'})_")
    signals_block = "\n".join(sig_lines) if sig_lines else "_none_"

    return f"""## Opportunity

**Category:** `{cand['category']}`
**Method type:** `{cand['method_type']}`
**Passive level:** `{cand['passive_level']}` &nbsp;|&nbsp; **ROI band:** `{cand['est_roi_band']}` &nbsp;|&nbsp; **Risk:** `{cand['risk_band']}`
**Time to setup:** `{cand['time_to_setup']}` &nbsp;|&nbsp; **Vibe-codability:** `{cand['vibe_codability_score']:.2f}` &nbsp;|&nbsp; **Score:** `{cand['score']:.3f}`

### Summary

{cand['summary'] or '_(no summary)_'}

## Funnel

- [x] **L2** scored
- [ ] **L3** demand-check (SEO/competition + landing + email capture)
- [ ] **L4** micro-MVP (vibe-coded from template, deployed, metrics)
- [ ] **L5** prod (real resources committed)

## Source signals

{signals_block}

## Notes / decisions

<!-- your hand goes here -->

---
_Candidate ID: {cand['id']} · auto-created by pipeline/track.py_
"""


def _create_issue(title: str, body: str, labels: list[str]) -> int | None:
    cmd = ["gh", "issue", "create", "--title", title, "--body", body]
    for lab in labels:
        cmd += ["--label", lab]
    try:
        out = subprocess.run(
            cmd, check=True, capture_output=True, text=True, timeout=60
        )
    except FileNotFoundError:
        print("[track] `gh` CLI not found; skipping issue creation.", file=sys.stderr)
        return None
    except subprocess.CalledProcessError as e:
        print(f"[track] gh failed: {e.stderr.strip()}", file=sys.stderr)
        return None
    # gh prints the issue URL on success: .../issues/42
    url = out.stdout.strip()
    if url.isdigit():
        return int(url)
    if "/issues/" in url:
        return int(url.rsplit("/issues/", 1)[1].split("#")[0].split("?")[0])
    return None
