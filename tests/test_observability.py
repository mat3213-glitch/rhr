"""Tests for pipeline/observability.py — Logger, metrics aggregation."""
import json
import tempfile
from pathlib import Path

from pipeline.observability import (
    AggregatedMetrics,
    Logger,
    RunMetrics,
    aggregate_logs,
)


class TestRunMetrics:
    def test_to_dict(self):
        m = RunMetrics(command="test", started_at="2026-01-01T00:00:00Z")
        d = m.to_dict()
        assert d["command"] == "test"
        assert d["status"] == "ok"
        assert d["duration_ms"] == 0.0
        assert d["errors"] == []

    def test_with_errors(self):
        m = RunMetrics(command="test", errors=["err1", "err2"])
        d = m.to_dict()
        assert len(d["errors"]) == 2


class TestLogger:
    def test_start_end_run(self, tmp_path):
        log = Logger(log_dir=tmp_path)
        run = log.start_run("test_cmd", key="value")
        assert run.command == "test_cmd"
        assert run.metadata == {"key": "value"}
        assert run.started_at.endswith("Z")

        run = log.end_run("ok")
        assert run.status == "ok"
        assert run.finished_at.endswith("Z")

    def test_inc_counters(self, tmp_path):
        log = Logger(log_dir=tmp_path)
        log.start_run("test")
        log.inc("rows_inserted", 5)
        log.inc("rows_inserted", 3)
        log.inc("rows_dropped", 2)
        run = log.end_run()
        assert run.rows_inserted == 8
        assert run.rows_dropped == 2

    def test_log_error(self, tmp_path):
        log = Logger(log_dir=tmp_path)
        log.start_run("test")
        log.log_error("something broke")
        run = log.end_run("error")
        assert "something broke" in run.errors
        assert run.status == "error"

    def test_creates_log_file(self, tmp_path):
        log = Logger(log_dir=tmp_path)
        log.start_run("test")
        log.end_run("ok")

        log_files = list(tmp_path.glob("runs-*.jsonl"))
        assert len(log_files) == 1
        with open(log_files[0]) as f:
            data = json.loads(f.readline())
        assert data["command"] == "test"
        assert data["status"] == "ok"

    def test_log_metric(self, tmp_path):
        log = Logger(log_dir=tmp_path)
        log.start_run("test")
        log.log_metric("signal_count", 42, source="hackernews")
        log.end_run()
        # Should not raise

    def test_end_without_start_raises(self, tmp_path):
        import pytest
        log = Logger(log_dir=tmp_path)
        with pytest.raises(RuntimeError, match="No active run"):
            log.end_run()


class TestAggregateLogs:
    def test_empty_dir(self, tmp_path):
        m = aggregate_logs(log_dir=tmp_path)
        assert m.total_runs == 0

    def test_aggregates_multiple_runs(self, tmp_path):
        log = Logger(log_dir=tmp_path)

        # Run 1
        log.start_run("scan:hackernews")
        log.inc("rows_processed", 100)
        log.inc("rows_inserted", 80)
        log.end_run("ok")

        # Run 2
        log.start_run("pipeline")
        log.inc("rows_inserted", 5)
        log.end_run("ok")

        # Run 3 (failed)
        log.start_run("scan:rss")
        log.log_error("connection timeout")
        log.end_run("error")

        m = aggregate_logs(log_dir=tmp_path, days=1)
        assert m.total_runs == 3
        assert m.successful_runs == 2
        assert m.failed_runs == 1
        assert m.total_rows_processed == 100
        assert m.total_rows_inserted == 85
        assert m.total_errors == 1
        assert m.runs_by_command["scan:hackernews"] == 1
        assert m.runs_by_command["pipeline"] == 1
        assert len(m.recent_runs) == 3

    def test_respects_days_filter(self, tmp_path):
        # Create an old log file
        old_file = tmp_path / "runs-2020-01-01.jsonl"
        old_file.write_text('{"command":"old","status":"ok","duration_ms":10}\n')

        log = Logger(log_dir=tmp_path)
        log.start_run("new")
        log.end_run("ok")

        m = aggregate_logs(log_dir=tmp_path, days=1)
        assert m.total_runs == 1  # only the new one
