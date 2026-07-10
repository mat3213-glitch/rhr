#!/usr/bin/env python3
"""RHR orchestrator — single CLI entry point.

Commands:
  init              Apply data/schema.sql (creates/updates the SQLite DB)
  scan [SOURCE]     Run collectors. With no arg: all enabled sources.
                    With a name (e.g. hackernews, rss): just that one.
  pipeline          normalize (already done at scan time) → dedup → classify → score
  score [--rescore] Re-score candidates (use after editing scoring/weights.yaml)
  track [--dry-run] [--top N]  Create GitHub issues for top candidates
  status            Print quick counts per funnel stage

Typical First Slice run:
  python run.py init
  python run.py scan
  python run.py pipeline
  python run.py track --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys

# ── Load .env before anything else (no python-dotenv dependency) ──────────────
_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.isfile(_env_path):
    with open(_env_path, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#"):
                continue
            if "=" not in _line:
                continue
            _key, _, _value = _line.partition("=")
            _key = _key.strip()
            _value = _value.strip().strip("\"'")
            os.environ.setdefault(_key, _value)

# Make sibling packages importable when running as `python run.py` from repo root.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import collectors  # noqa: E402,F401  (registers all collectors)
from collectors.base import CollectorError, get_collector  # noqa: E402
from config_loader import (  # noqa: E402
    DATA_DIR,
    DB_PATH,
    db,
    load_sources,
    log_run,
)
from pipeline.classify import classify_pending, llm_backend  # noqa: E402
from pipeline.dedup import dedup_signals  # noqa: E402
from pipeline.normalize import normalize_and_store  # noqa: E402
from pipeline.score import score_pending  # noqa: E402
from pipeline.track import track as track_candidates  # noqa: E402
from sandbox.demand_check import run_demand_check, list_demand_checks  # noqa: E402
from sandbox.mvp_templates import generate_mvp, list_mvps, list_templates  # noqa: E402
from sandbox.metrics import (  # noqa: E402
    collect_metrics, set_verdict, graduate_candidate, kill_candidate,
)
from pipeline.observability import logger, aggregate_logs  # noqa: E402


def cmd_init(_: argparse.Namespace) -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    schema = os.path.join(os.path.dirname(__file__), "data", "schema.sql")
    conn = db()
    with open(schema, encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.commit()
    print(f"[init] schema applied to {DB_PATH}")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    sources_cfg = load_sources().get("sources", {})
    names = [args.source] if args.source else list(sources_cfg.keys())
    conn = db()
    run = logger.start_run("scan", sources=names)
    total_in = total_kept = 0
    for name in names:
        cfg = sources_cfg.get(name)
        if not cfg:
            print(f"[scan] unknown source {name!r}; check config/sources.yaml")
            continue
        if not cfg.get("enabled", False):
            print(f"[scan] {name}: disabled, skipping")
            continue
        try:
            coll = get_collector(cfg["type"], cfg.get("params", {}))
        except CollectorError as e:
            print(f"[scan] {name}: {e}")
            continue
        print(f"[scan] {name}: fetching via {cfg['type']}...")
        try:
            items = coll.fetch()
        except Exception as e:
            print(f"[scan] {name}: FAILED ({e})")
            logger.log_error(f"scan:{name}: {e}")
            log_run(conn, f"scan:{name}", source=name, status="error", message=str(e))
            continue
        stats = normalize_and_store(conn, items)
        dups = dedup_signals(conn)
        logger.inc("rows_processed", len(items))
        logger.inc("rows_inserted", stats["inserted"])
        logger.inc("rows_dropped", stats["dropped_l0"])
        print(
            f"[scan] {name}: fetched={len(items)} kept={stats['inserted']} "
            f"skipped_existing={stats['skipped_existing']} dropped_l0={stats['dropped_l0']} new_duplicates={dups}"
        )
        log_run(
            conn,
            f"scan:{name}",
            source=name,
            inserted=stats["inserted"],
            message=f"fetched={len(items)} dropped_l0={stats['dropped_l0']}",
        )
        total_in += len(items)
        total_kept += stats["inserted"]
    run = logger.end_run("ok")
    print(f"[scan] done. fetched={total_in} newly_kept={total_kept}")
    return 0


def cmd_pipeline(_: argparse.Namespace) -> int:
    conn = db()
    run = logger.start_run("pipeline")
    try:
        dups = dedup_signals(conn)
        logger.inc("rows_dropped", dups)
        print(f"[pipeline] dedup: flagged {dups} duplicates")

        cls = classify_pending(conn, backend=llm_backend)
        logger.inc("rows_inserted", cls["candidates_created"])
        logger.inc("rows_dropped", cls["signals_skipped"])
        print(f"[pipeline] classify: created {cls['candidates_created']} candidates, "
              f"skipped {cls['signals_skipped']} weak signals")

        n = score_pending(conn)
        logger.inc("rows_updated", n)
        print(f"[pipeline] score: scored {n} candidates")

        run = logger.end_run("ok")
        try:
            _print_top(conn)
        except Exception:
            pass
        return 0
    except Exception as e:
        logger.log_error(str(e))
        try:
            logger.end_run("error")
        except RuntimeError:
            pass
        raise


def cmd_score(args: argparse.Namespace) -> int:
    conn = db()
    n = score_pending(conn, rescore=args.rescore)
    print(f"[score] scored {n} candidates (rescore={args.rescore})")
    _print_top(conn)
    return 0


def cmd_track(args: argparse.Namespace) -> int:
    conn = db()
    res = track_candidates(conn, top_n=args.top, dry_run=args.dry_run)
    print(f"[track] tracked={res['tracked']} considered={res['considered']} "
          f"(dry_run={args.dry_run})")
    return 0


def cmd_dashboard(_: argparse.Namespace) -> int:
    from dashboard.build import build, OUT
    html = build()
    OUT.write_text(html, encoding="utf-8")
    print(f"[dashboard] wrote {OUT} ({len(html)} bytes)")
    return 0


def cmd_demand_check(args: argparse.Namespace) -> int:
    conn = db()
    if args.list:
        runs = list_demand_checks(conn)
        if not runs:
            print("  (no demand checks yet)")
            return 0
        for r in runs:
            print(f"  #{r['id']:>4}  cand={r['candidate_id']}  verdict={r['verdict']}  "
                  f"score={r['score'] or 0:.3f}  {r['title'][:50]}")
        return 0
    if not args.candidate_id:
        print("[demand_check] provide --candidate ID or --list")
        return 1
    result = run_demand_check(conn, args.candidate_id)
    print(f"[demand_check] candidate #{result.candidate_id}: "
          f"seo={result.seo_score:.2f} competition={result.competition_level} "
          f"verdict={result.verdict}")
    if result.landing_html:
        out_path = DATA_DIR / f"landing_{result.candidate_id}.html"
        out_path.write_text(result.landing_html, encoding="utf-8")
        print(f"  landing page: {out_path}")
    return 0


def cmd_mvp(args: argparse.Namespace) -> int:
    conn = db()
    if args.templates:
        for name, t in list_templates().items():
            print(f"  {name:20} {t['name']}")
            print(f"  {'':20} {t['description']}")
            print(f"  {'':20} files: {', '.join(t['files'])}")
            print()
        return 0
    if args.list:
        runs = list_mvps(conn)
        if not runs:
            print("  (no MVPs yet)")
            return 0
        for r in runs:
            print(f"  #{r['id']:>4}  cand={r['candidate_id']}  template={r['method_type']}  "
                  f"verdict={r['verdict']}  {r['title'][:50]}")
        return 0
    if not args.candidate_id:
        print("[mvp] provide --candidate ID, --list, or --templates")
        return 1
    result = generate_mvp(conn, args.candidate_id)
    print(f"[mvp] candidate #{result.candidate_id}: template={result.template_name} "
          f"files={result.files_generated}")
    return 0


def cmd_sandbox_status(_: argparse.Namespace) -> int:
    conn = db()
    m = collect_metrics(conn)
    print(f"  sandbox runs:      {m.total_runs} (demand_check={m.demand_checks}, mvp={m.micro_mvps})")
    print(f"  verdicts:          go={m.verdicts['go']}  no_go={m.verdicts['no_go']}  pending={m.verdicts['pending']}")
    print(f"  total visits:      {m.total_visits}")
    print(f"  total signups:     {m.total_signups}")
    print(f"  conversion:        {m.overall_conversion:.1%}")
    return 0


def cmd_verdict(args: argparse.Namespace) -> int:
    conn = db()
    set_verdict(conn, args.run_id, args.verdict, args.reason)
    print(f"[verdict] run #{args.run_id} → {args.verdict}")
    if args.verdict == "go" and args.graduate:
        if not args.candidate_id:
            print("[verdict] --graduate requires --candidate ID", file=sys.stderr)
            return 1
        graduate_candidate(conn, args.candidate_id)
        print(f"  graduated candidate #{args.candidate_id} to L5-prod")
    if args.verdict == "no_go" and args.reason:
        if args.candidate_id:
            kill_candidate(conn, args.candidate_id, args.reason)
            print(f"  killed candidate #{args.candidate_id}: {args.reason}")
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    m = aggregate_logs(days=args.days)
    print(f"  runs (last {args.days} days):  {m.total_runs}")
    print(f"  successful:        {m.successful_runs}")
    print(f"  failed:            {m.failed_runs}")
    print(f"  avg duration:      {m.avg_duration_ms:.0f}ms")
    print(f"  rows processed:    {m.total_rows_processed}")
    print(f"  rows inserted:     {m.total_rows_inserted}")
    print(f"  errors:            {m.total_errors}")
    if m.runs_by_command:
        print("  by command:")
        for cmd, count in sorted(m.runs_by_command.items(), key=lambda x: -x[1]):
            print(f"    {cmd:30} {count}")
    if m.recent_runs:
        print("  recent runs:")
        for r in m.recent_runs[-5:]:
            print(f"    {r['started_at']}  {r['command']:20}  {r['status']}  {r.get('duration_ms', 0):.0f}ms")
    return 0


def cmd_ingest_stdin(_: argparse.Namespace) -> int:
    """Read JSON lines from stdin and insert as signals."""
    import json as _json
    from models import RawItem
    from pipeline.normalize import normalize_and_store

    conn = db()
    items = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            d = _json.loads(line)
            items.append(RawItem(**d))
        except Exception as e:
            print(f"[ingest] skipped line: {e}", file=sys.stderr)

    if not items:
        print("[ingest] no items to ingest")
        return 0

    stats = normalize_and_store(conn, items)
    dups = dedup_signals(conn)
    print(f"[ingest] inserted={stats['inserted']} skipped_existing={stats['skipped_existing']} "
          f"dropped_l0={stats['dropped_l0']} new_duplicates={dups}")
    return 0


def cmd_status(_: argparse.Namespace) -> int:
    conn = db()
    for label, q in [
        ("signals (kept)", "SELECT COUNT(*) c FROM signals WHERE l1_status='kept'"),
        ("signals (duplicate)", "SELECT COUNT(*) c FROM signals WHERE l1_status='duplicate'"),
        ("signals (low_quality)", "SELECT COUNT(*) c FROM signals WHERE l1_status='low_quality'"),
        ("candidates (total)", "SELECT COUNT(*) c FROM candidates"),
    ]:
        c = conn.execute(q).fetchone()["c"]
        print(f"  {label:30} {c}")
    print("  candidates by stage:")
    for r in conn.execute(
        "SELECT funnel_stage, COUNT(*) c FROM candidates GROUP BY funnel_stage ORDER BY c DESC"
    ):
        print(f"    {r['funnel_stage']:20} {r['c']}")
    print("  top 5 candidates:")
    _print_top(conn, limit=5)
    return 0


def _print_top(conn, limit: int = 10):
    rows = conn.execute(
        """SELECT id, score, category, method_type, passive_level, title
             FROM candidates WHERE score IS NOT NULL
             ORDER BY score DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    if not rows:
        print("  (no scored candidates yet)")
        return
    for r in rows:
        print(f"  #{r['id']:>4}  score={r['score']:.3f}  "
              f"[{r['category']}/{r['method_type']}/{r['passive_level']}]  {r['title'][:70]}")


def main() -> int:
    p = argparse.ArgumentParser(prog="rhr", description="Rabbit Hole Radar")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="apply SQLite schema")

    sp = sub.add_parser("scan", help="run collectors")
    sp.add_argument("source", nargs="?", help="source name (default: all enabled)")

    sub.add_parser("pipeline", help="dedup + classify + score")

    sp = sub.add_parser("score", help="score pending candidates")
    sp.add_argument("--rescore", action="store_true", help="recompute all scores")

    sp = sub.add_parser("track", help="create GitHub issues for top candidates")
    sp.add_argument("--dry-run", action="store_true")
    sp.add_argument("--top", type=int, default=5)

    sub.add_parser("status", help="show counts and top candidates")
    sub.add_parser("dashboard", help="build static dashboard from DB")

    sp = sub.add_parser("demand-check", help="L3 demand-check for a candidate")
    sp.add_argument("--candidate", dest="candidate_id", type=int, help="candidate ID")
    sp.add_argument("--list", action="store_true", help="list demand checks")

    sp = sub.add_parser("mvp", help="L4 micro-MVP generation")
    sp.add_argument("--candidate", dest="candidate_id", type=int, help="candidate ID")
    sp.add_argument("--list", action="store_true", help="list MVPs")
    sp.add_argument("--templates", action="store_true", help="list available templates")

    sub.add_parser("sandbox-status", help="show sandbox metrics")

    sp = sub.add_parser("verdict", help="set verdict on a sandbox run")
    sp.add_argument("run_id", type=int, help="sandbox run ID")
    sp.add_argument("verdict", choices=["go", "no_go", "pending"], help="verdict")
    sp.add_argument("--reason", help="verdict reason")
    sp.add_argument("--candidate", dest="candidate_id", type=int, help="candidate ID for graduate/kill")
    sp.add_argument("--graduate", action="store_true", help="graduate candidate to L5-prod")

    sp = sub.add_parser("metrics", help="show aggregated run metrics")
    sp.add_argument("--days", type=int, default=7, help="look back N days (default: 7)")

    sub.add_parser("ingest-stdin", help="ingest JSON lines from stdin as signals")

    args = p.parse_args()
    handlers = {
        "init": cmd_init,
        "scan": cmd_scan,
        "pipeline": cmd_pipeline,
        "score": cmd_score,
        "track": cmd_track,
        "status": cmd_status,
        "dashboard": cmd_dashboard,
        "demand-check": cmd_demand_check,
        "mvp": cmd_mvp,
        "sandbox-status": cmd_sandbox_status,
        "verdict": cmd_verdict,
        "metrics": cmd_metrics,
        "ingest-stdin": cmd_ingest_stdin,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
