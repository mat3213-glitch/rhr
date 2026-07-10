"""Tests for run.py — CLI command handlers."""
from __future__ import annotations

import os
import sys
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from config_loader import DB_PATH


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Create a fresh DB in tmp_path and patch db() to use it."""
    import sqlite3
    from pathlib import Path
    schema_path = Path(__file__).parent.parent / "data" / "schema.sql"
    test_db = tmp_path / "test.db"
    conn = sqlite3.connect(test_db)
    conn.executescript(schema_path.read_text())
    conn.close()
    monkeypatch.setattr("run.DB_PATH", test_db)
    monkeypatch.setattr("run.DATA_DIR", tmp_path)
    monkeypatch.setattr("config_loader.DB_PATH", test_db)
    return test_db


class TestCmdInit:
    def test_init_creates_schema(self, tmp_path, monkeypatch):
        monkeypatch.setattr("run.DATA_DIR", tmp_path)
        monkeypatch.setattr("run.DB_PATH", tmp_path / "rhr.db")
        monkeypatch.setattr("config_loader.DB_PATH", tmp_path / "rhr.db")
        import run
        args = MagicMock()
        rc = run.cmd_init(args)
        assert rc == 0
        assert (tmp_path / "rhr.db").exists()
        import sqlite3
        conn = sqlite3.connect(tmp_path / "rhr.db")
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        conn.close()
        assert "candidates" in tables
        assert "signals" in tables


class TestCmdScan:
    def test_scan_unknown_source(self, fresh_db, monkeypatch):
        monkeypatch.setattr("run.load_sources", lambda: {"sources": {}})
        import run
        args = MagicMock()
        args.source = "nonexistent"
        rc = run.cmd_scan(args)
        assert rc == 0

    def test_scan_disabled_source(self, fresh_db, monkeypatch):
        monkeypatch.setattr("run.load_sources", lambda: {
            "sources": {"test": {"enabled": False, "type": "rss"}}
        })
        import run
        args = MagicMock()
        args.source = "test"
        rc = run.cmd_scan(args)
        assert rc == 0


class TestCmdPipeline:
    def test_pipeline_empty_db(self, fresh_db, monkeypatch):
        monkeypatch.setattr("run.load_sources", lambda: {"sources": {}})
        import run
        args = MagicMock()
        rc = run.cmd_pipeline(args)
        assert rc == 0


class TestCmdStatus:
    def test_status_empty_db(self, fresh_db, monkeypatch, capsys):
        import run
        args = MagicMock()
        rc = run.cmd_status(args)
        assert rc == 0
        captured = capsys.readouterr()
        assert "signals" in captured.out


class TestCmdIngestStdin:
    def test_ingest_empty_stdin(self, fresh_db, monkeypatch):
        import run
        monkeypatch.setattr("sys.stdin", StringIO(""))
        args = MagicMock()
        rc = run.cmd_ingest_stdin(args)
        assert rc == 0

    def test_ingest_valid_json(self, fresh_db, monkeypatch):
        import run
        line = '{"source":"test","source_item_id":"t1","title":"Test","url":"http://x.com"}'
        monkeypatch.setattr("sys.stdin", StringIO(line))
        args = MagicMock()
        rc = run.cmd_ingest_stdin(args)
        assert rc == 0


class TestCmdVerdict:
    def test_verdict_without_candidate_fails(self, fresh_db, monkeypatch):
        import run
        args = MagicMock()
        args.run_id = 1
        args.verdict = "go"
        args.graduate = True
        args.candidate_id = None
        args.reason = None
        rc = run.cmd_verdict(args)
        assert rc == 1


class TestEnvLoading:
    def test_quotes_stripped(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text('TEST_KEY="hello"\nOTHER_KEY=\'world\'\n')
        monkeypatch.setattr("os.environ", {})
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if not line or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip("\"'")
                os.environ.setdefault(key, value)
        assert os.environ.get("TEST_KEY") == "hello"
        assert os.environ.get("OTHER_KEY") == "world"
