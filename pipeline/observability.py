"""Observability: structured JSON logging and metrics aggregation.

Provides structured logging for all pipeline stages, run metrics tracking,
and performance monitoring. Outputs JSON logs for easy aggregation.
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG_DIR = Path(__file__).resolve().parent.parent / "data" / "logs"


@dataclass
class RunMetrics:
    """Metrics for a single pipeline run."""
    command: str
    started_at: str = ""
    finished_at: str = ""
    duration_ms: float = 0.0
    status: str = "ok"
    rows_processed: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_dropped: int = 0
    errors: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "command": self.command,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": round(self.duration_ms, 1),
            "status": self.status,
            "rows_processed": self.rows_processed,
            "rows_inserted": self.rows_inserted,
            "rows_updated": self.rows_updated,
            "rows_dropped": self.rows_dropped,
            "errors": self.errors,
            "metadata": self.metadata,
        }


class Logger:
    """Structured JSON logger for pipeline operations."""

    def __init__(self, log_dir: Path | None = None):
        self.log_dir = log_dir or LOG_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._current_run: RunMetrics | None = None

    def start_run(self, command: str, **metadata) -> RunMetrics:
        """Start tracking a new run."""
        self._current_run = RunMetrics(
            command=command,
            started_at=_utcnow(),
            metadata=metadata,
        )
        self._log("run_start", command=command, metadata=metadata)
        return self._current_run

    def end_run(self, status: str = "ok") -> RunMetrics:
        """End the current run and flush to disk."""
        if not self._current_run:
            raise RuntimeError("No active run to end")

        self._current_run.finished_at = _utcnow()
        self._current_run.status = status

        # Calculate duration
        try:
            start = datetime.fromisoformat(self._current_run.started_at.replace("Z", "+00:00"))
            end = datetime.fromisoformat(self._current_run.finished_at.replace("Z", "+00:00"))
            self._current_run.duration_ms = (end - start).total_seconds() * 1000
        except (ValueError, TypeError):
            pass

        self._log("run_end", **self._current_run.to_dict())

        # Append to daily log file
        self._append_log(self._current_run)

        run = self._current_run
        self._current_run = None
        return run

    def log(self, event: str, **kwargs) -> None:
        """Log a structured event."""
        self._log(event, **kwargs)

    def log_metric(self, name: str, value: Any, **tags) -> None:
        """Log a metric data point."""
        self._log("metric", name=name, value=value, tags=tags)

    def log_error(self, error: str, context: dict | None = None) -> None:
        """Log an error, attaching to current run if active."""
        if self._current_run:
            self._current_run.errors.append(error)
        self._log("error", errorerror=error, context=context or {})

    def inc(self, field: str, amount: int = 1) -> None:
        """Increment a counter on the current run."""
        if not self._current_run:
            return
        current = getattr(self._current_run, field, None)
        if isinstance(current, int):
            setattr(self._current_run, field, current + amount)

    def _log(self, event: str, **kwargs) -> None:
        entry = {
            "ts": _utcnow(),
            "event": event,
            **kwargs,
        }
        line = json.dumps(entry, ensure_ascii=False, default=str)
        # Write to stdout for CI/CD capture
        print(f"  [obs] {line}")

    def _append_log(self, run: RunMetrics) -> None:
        """Append run metrics to daily log file."""
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        log_file = self.log_dir / f"runs-{date_str}.jsonl"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(run.to_dict(), ensure_ascii=False) + "\n")


def _utcnow() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Metrics aggregation ────────────────────────────────────────────────────


@dataclass
class AggregatedMetrics:
    """Aggregated metrics across multiple runs."""
    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    total_duration_ms: float = 0.0
    avg_duration_ms: float = 0.0
    total_rows_processed: int = 0
    total_rows_inserted: int = 0
    total_errors: int = 0
    runs_by_command: dict = field(default_factory=dict)
    recent_runs: list[dict] = field(default_factory=list)


def aggregate_logs(log_dir: Path | None = None, days: int = 7) -> AggregatedMetrics:
    """Aggregate metrics from log files over the last N days."""
    log_dir = log_dir or LOG_DIR
    metrics = AggregatedMetrics()

    if not log_dir.exists():
        return metrics

    from datetime import timedelta
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    for log_file in sorted(log_dir.glob("runs-*.jsonl")):
        # Parse date from filename
        try:
            date_str = log_file.stem.replace("runs-", "")
            file_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            if file_date < cutoff:
                continue
        except ValueError:
            continue

        with open(log_file, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    run = json.loads(line)
                except json.JSONDecodeError:
                    continue

                metrics.total_runs += 1
                if run.get("status") == "ok":
                    metrics.successful_runs += 1
                else:
                    metrics.failed_runs += 1

                metrics.total_duration_ms += run.get("duration_ms", 0)
                metrics.total_rows_processed += run.get("rows_processed", 0)
                metrics.total_rows_inserted += run.get("rows_inserted", 0)
                metrics.total_errors += len(run.get("errors", []))

                cmd = run.get("command", "unknown")
                metrics.runs_by_command[cmd] = metrics.runs_by_command.get(cmd, 0) + 1

                metrics.recent_runs.append(run)

    if metrics.total_runs > 0:
        metrics.avg_duration_ms = metrics.total_duration_ms / metrics.total_runs

    # Keep only last 20 recent runs
    metrics.recent_runs = metrics.recent_runs[-20:]

    return metrics


# ── Singleton logger ───────────────────────────────────────────────────────

logger = Logger()
