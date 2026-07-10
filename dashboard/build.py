#!/usr/bin/env python3
"""Build static dashboard from the RHR SQLite database.

Usage:
    python dashboard/build.py

Reads data/rhr.db and generates dashboard/index.html.
Run after each pipeline pass or via GitHub Actions.
"""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "rhr.db"
OUT = Path(__file__).resolve().parent / "index.html"


def query(conn: sqlite3.Connection, sql: str, params=()) -> list[dict]:
    conn.row_factory = sqlite3.Row
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def query_val(conn: sqlite3.Connection, sql: str, params=()):
    return conn.execute(sql, params).fetchone()[0]


def build(db_path=None) -> str:
    if db_path is None:
        db_path = DB_PATH
    if not db_path.exists():
        return _render(empty=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    # ── funnel counts ──
    signals_kept = query_val(conn, "SELECT COUNT(*) FROM signals WHERE l1_status='kept'")
    signals_dup = query_val(conn, "SELECT COUNT(*) FROM signals WHERE l1_status='duplicate'")
    signals_lq = query_val(conn, "SELECT COUNT(*) FROM signals WHERE l1_status='low_quality'")
    signals_total = query_val(conn, "SELECT COUNT(*) FROM signals")

    # ── candidates by stage ──
    stage_rows = query(conn, "SELECT funnel_stage, COUNT(*) c FROM candidates GROUP BY funnel_stage ORDER BY c DESC")
    stages = {r["funnel_stage"]: r["c"] for r in stage_rows}
    candidates_total = query_val(conn, "SELECT COUNT(*) FROM candidates")

    # ── candidates by category ──
    cat_rows = query(conn, "SELECT category, COUNT(*) c FROM candidates GROUP BY category ORDER BY c DESC")
    categories = {r["category"] or "unknown": r["c"] for r in cat_rows}

    # ── candidates by method ──
    method_rows = query(conn, "SELECT method_type, COUNT(*) c FROM candidates GROUP BY method_type ORDER BY c DESC")
    methods = {r["method_type"] or "unknown": r["c"] for r in method_rows}

    # ── signals by source ──
    source_rows = query(conn, "SELECT source, COUNT(*) c FROM signals GROUP BY source ORDER BY c DESC")
    sources = {r["source"]: r["c"] for r in source_rows}

    # ── top candidates ──
    top = query(conn, """SELECT id, title, category, method_type, passive_level,
                         est_roi_band, risk_band, score, funnel_stage, github_issue_number,
                         first_seen_at
                    FROM candidates WHERE score IS NOT NULL
                    ORDER BY score DESC LIMIT 20""")

    # ── recent run log ──
    runs = query(conn, """SELECT command, source, status, started_at,
                          rows_inserted, message
                     FROM run_log ORDER BY id DESC LIMIT 15""")

    # ── score distribution ──
    score_hist = query(conn, """SELECT
        CASE
            WHEN score >= 0.8 THEN '0.8-1.0'
            WHEN score >= 0.6 THEN '0.6-0.8'
            WHEN score >= 0.4 THEN '0.4-0.6'
            WHEN score >= 0.2 THEN '0.2-0.4'
            ELSE '0.0-0.2'
        END bucket,
        COUNT(*) c
        FROM candidates WHERE score IS NOT NULL
        GROUP BY bucket ORDER BY bucket""")
    score_dist = {r["bucket"]: r["c"] for r in score_hist}

    conn.close()

    return _render(
        empty=False,
        signals_total=signals_total,
        signals_kept=signals_kept,
        signals_dup=signals_dup,
        signals_lq=signals_lq,
        candidates_total=candidates_total,
        stages=stages,
        categories=categories,
        methods=methods,
        sources=sources,
        top=top,
        runs=runs,
        score_dist=score_dist,
    )


def _render(**ctx) -> str:
    empty = ctx.get("empty", True)
    signals_total = ctx.get("signals_total", 0)
    signals_kept = ctx.get("signals_kept", 0)
    signals_dup = ctx.get("signals_dup", 0)
    signals_lq = ctx.get("signals_lq", 0)
    candidates_total = ctx.get("candidates_total", 0)
    stages = ctx.get("stages", {})
    categories = ctx.get("categories", {})
    methods = ctx.get("methods", {})
    sources = ctx.get("sources", {})
    top = ctx.get("top", [])
    runs = ctx.get("runs", [])
    score_dist = ctx.get("score_dist", {})

    def _safe_json(obj):
        return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")

    stage_labels = _safe_json(list(stages.keys()))
    stage_values = _safe_json(list(stages.values()))
    cat_labels = _safe_json(list(categories.keys()))
    cat_values = _safe_json(list(categories.values()))
    method_labels = _safe_json(list(methods.keys()))
    method_values = _safe_json(list(methods.values()))
    source_labels = _safe_json(list(sources.keys()))
    source_values = _safe_json(list(sources.values()))
    score_labels = _safe_json(list(score_dist.keys()))
    score_values = _safe_json(list(score_dist.values()))

    top_rows = ""
    for t in top:
        issue_link = ""
        if t.get("github_issue_number"):
            issue_link = f'<a href="https://github.com/{os.environ.get("GITHUB_REPOSITORY", "owner/rhr")}/issues/{t["github_issue_number"]}" target="_blank">#{t["github_issue_number"]}</a>'
        date_val = (t.get("first_seen_at") or "")[:10]
        top_rows += f"""<tr data-date="{date_val}">
            <td>{t['id']}</td>
            <td class="score">{t['score']:.3f}</td>
            <td>{_esc(t['title'][:80])}</td>
            <td><span class="badge cat-{_esc(t['category'] or 'other')}">{_esc(t['category'] or '?')}</span></td>
            <td>{_esc(t['method_type'] or '?')}</td>
            <td>{_esc(t['passive_level'] or '?')}</td>
            <td>{_esc(t['funnel_stage'])}</td>
            <td>{issue_link}</td>
        </tr>"""

    run_rows = ""
    for r in runs:
        status_cls = "ok" if r["status"] == "ok" else "err"
        date_val = (r.get("started_at") or "")[:10]
        run_rows += f"""<tr data-date="{date_val}">
            <td><span class="status {status_cls}">{_esc(r['status'])}</span></td>
            <td>{_esc(r['command'])}</td>
            <td>{_esc(r.get('source') or '—')}</td>
            <td>{r['rows_inserted'] or 0}</td>
            <td class="ts">{_esc(r['started_at'])}</td>
            <td class="msg">{_esc((r.get('message') or '')[:60])}</td>
        </tr>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>RHR — Pipeline Dashboard</title>
<style>
  :root {{
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --text: #e6edf3; --muted: #8b949e; --accent: #58a6ff;
    --green: #3fb950; --yellow: #d29922; --red: #f85149; --purple: #bc8cff;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ background: var(--bg); color: var(--text); font-family: -apple-system, system-ui, sans-serif; font-size: 14px; padding: 24px; }}
  h1 {{ font-size: 22px; margin-bottom: 4px; }}
  h1 span {{ color: var(--muted); font-weight: 400; font-size: 14px; }}
  .subtitle {{ color: var(--muted); margin-bottom: 24px; font-size: 13px; }}
  .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 24px; }}
  .card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }}
  .card h3 {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; }}
  .card .big {{ font-size: 32px; font-weight: 700; }}
  .card .sub {{ color: var(--muted); font-size: 12px; margin-top: 4px; }}
  .charts {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; margin-bottom: 24px; }}
  .chart-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }}
  .chart-card h3 {{ color: var(--muted); font-size: 12px; text-transform: uppercase; margin-bottom: 12px; }}
  canvas {{ max-height: 220px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ text-align: left; color: var(--muted); font-size: 11px; text-transform: uppercase; padding: 8px 10px; border-bottom: 1px solid var(--border); }}
  td {{ padding: 7px 10px; border-bottom: 1px solid var(--border); }}
  tr:hover {{ background: rgba(88,166,255,0.05); }}
  .score {{ font-weight: 700; color: var(--green); font-variant-numeric: tabular-nums; }}
  .badge {{ padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }}
  .cat-crypto_defi {{ background: #1f3a2f; color: #3fb950; }}
  .cat-digital_asset {{ background: #1a2744; color: #58a6ff; }}
  .cat-arbitrage {{ background: #3b2e1a; color: #d29922; }}
  .cat-algo {{ background: #2d1f3d; color: #bc8cff; }}
  .cat-other {{ background: #21262d; color: #8b949e; }}
  .status {{ padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }}
  .status.ok {{ background: #1f3a2f; color: #3fb950; }}
  .status.err {{ background: #3d1f1f; color: #f85149; }}
  .ts {{ color: var(--muted); font-size: 12px; }}
  .msg {{ color: var(--muted); font-size: 12px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  a {{ color: var(--accent); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .section {{ margin-bottom: 24px; }}
  .section h2 {{ font-size: 16px; margin-bottom: 12px; }}
  .empty {{ text-align: center; padding: 80px 20px; color: var(--muted); }}
  .empty h2 {{ font-size: 20px; margin-bottom: 8px; color: var(--text); }}
  .filter-bar {{ display: flex; gap: 12px; align-items: center; margin-bottom: 16px; flex-wrap: wrap; }}
  .filter-bar label {{ color: var(--muted); font-size: 12px; text-transform: uppercase; }}
  .filter-bar input[type="date"] {{ background: var(--surface); border: 1px solid var(--border); color: var(--text); padding: 6px 10px; border-radius: 6px; font-size: 13px; }}
  .filter-bar input[type="date"]::-webkit-calendar-picker-indicator {{ filter: invert(0.7); }}
  .filter-bar .btn {{ background: var(--border); color: var(--text); border: none; padding: 6px 14px; border-radius: 6px; cursor: pointer; font-size: 13px; }}
  .filter-bar .btn:hover {{ background: #484f58; }}
  .filter-bar .count {{ color: var(--muted); font-size: 12px; margin-left: 8px; }}
</style>
</head>
<body>
<h1>Rabbit Hole Radar <span>/ pipeline dashboard</span></h1>
<p class="subtitle">Auto-generated from <code>data/rhr.db</code> &middot; GitHub Actions deploys this page on every pipeline run</p>

{_empty_state() if empty else _content(signals_total, signals_kept, signals_dup, signals_lq,
    candidates_total, stages, top_rows, run_rows,
    stage_labels, stage_values, cat_labels, cat_values,
    method_labels, method_values, source_labels, source_values,
    score_labels, score_values)}
</body>
</html>"""


def _empty_state() -> str:
    return """<div class="empty">
  <h2>No data yet</h2>
  <p>Run <code>python run.py scan</code> and <code>python run.py pipeline</code> to populate the database.</p>
</div>"""


def _content(signals_total, signals_kept, signals_dup, signals_lq,
             candidates_total, stages, top_rows, run_rows,
             stage_labels, stage_values, cat_labels, cat_values,
             method_labels, method_values, source_labels, source_values,
             score_labels, score_values) -> str:
    stage_bars = "".join(
        f'<div class="card"><h3>{_esc(s)}</h3><div class="big">{c}</div></div>'
        for s, c in stages.items()
    )
    return f"""
<div class="filter-bar">
  <label>From</label>
  <input type="date" id="dateFrom">
  <label>To</label>
  <input type="date" id="dateTo">
  <button class="btn" onclick="applyFilter()">Filter</button>
  <button class="btn" onclick="clearFilter()">Clear</button>
  <span class="count" id="filterCount"></span>
</div>

<div class="grid">
  <div class="card"><h3>Total signals</h3><div class="big">{signals_total}</div><div class="sub">kept {signals_kept} · dup {signals_dup} · low_quality {signals_lq}</div></div>
  <div class="card"><h3>Candidates</h3><div class="big">{candidates_total}</div><div class="sub">{len(stages)} funnel stages</div></div>
</div>

<div class="section">
  <h2>Funnel stages</h2>
  <div class="grid">{stage_bars}</div>
</div>

<div class="charts">
  <div class="chart-card"><h3>Signals by source</h3><canvas id="srcChart"></canvas></div>
  <div class="chart-card"><h3>Candidates by category</h3><canvas id="catChart"></canvas></div>
  <div class="chart-card"><h3>Candidates by method</h3><canvas id="methodChart"></canvas></div>
  <div class="chart-card"><h3>Score distribution</h3><canvas id="scoreChart"></canvas></div>
</div>

<div class="section">
  <h2>Top candidates</h2>
  <div class="card" style="overflow-x:auto">
    <table>
      <thead><tr><th>#</th><th>Score</th><th>Title</th><th>Category</th><th>Method</th><th>Passive</th><th>Stage</th><th>Issue</th></tr></thead>
      <tbody>{top_rows}</tbody>
    </table>
  </div>
</div>

<div class="section">
  <h2>Recent runs</h2>
  <div class="card" style="overflow-x:auto">
    <table>
      <thead><tr><th>Status</th><th>Command</th><th>Source</th><th>Inserted</th><th>Time</th><th>Message</th></tr></thead>
      <tbody>{run_rows}</tbody>
    </table>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<script>
(function() {{
  var C = function(id) {{ return document.getElementById(id).getContext('2d'); }};
  var opts = {{ responsive: true, plugins: {{ legend: {{ display: false }} }} }};
  var colors = ['#58a6ff','#3fb950','#d29922','#bc8cff','#f85149','#79c0ff','#56d364','#e3b341'];

  new Chart(C('srcChart'), {{ type:'doughnut', data:{{ labels:{source_labels}, datasets:[{{ data:{source_values}, backgroundColor:colors }}] }}, options:opts }});
  new Chart(C('catChart'), {{ type:'doughnut', data:{{ labels:{cat_labels}, datasets:[{{ data:{cat_values}, backgroundColor:colors }}] }}, options:opts }});
  new Chart(C('methodChart'), {{ type:'bar', data:{{ labels:{method_labels}, datasets:[{{ data:{method_values}, backgroundColor:'#58a6ff' }}] }}, options:{{ ...opts, indexAxis:'y' }} }});
  new Chart(C('scoreChart'), {{ type:'bar', data:{{ labels:{score_labels}, datasets:[{{ data:{score_values}, backgroundColor:'#3fb950' }}] }}, options:opts }});

  window.applyFilter = function() {{
    var from = document.getElementById('dateFrom').value;
    var to = document.getElementById('dateTo').value;
    var rows = document.querySelectorAll('tr[data-date]');
    var shown = 0;
    rows.forEach(function(r) {{
      var d = r.getAttribute('data-date');
      if (!d) {{ r.style.display = ''; shown++; return; }}
      var show = true;
      if (from && d < from) show = false;
      if (to && d > to) show = false;
      r.style.display = show ? '' : 'none';
      if (show) shown++;
    }});
    document.getElementById('filterCount').textContent = shown + ' rows shown';
  }};

  window.clearFilter = function() {{
    document.getElementById('dateFrom').value = '';
    document.getElementById('dateTo').value = '';
    document.querySelectorAll('tr[data-date]').forEach(function(r) {{ r.style.display = ''; }});
    document.getElementById('filterCount').textContent = '';
  }};
}})();
</script>"""


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


if __name__ == "__main__":
    html = build()
    OUT.write_text(html, encoding="utf-8")
    print(f"[dashboard] wrote {OUT} ({len(html)} bytes)")
