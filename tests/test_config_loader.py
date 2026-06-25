"""Tests for config_loader.py — as_json, flattened_keywords, log_run."""
import json

from config_loader import as_json, flattened_keywords, log_run


class TestAsJson:
    def test_list(self):
        assert as_json(["a", "b"]) == '["a", "b"]'

    def test_dict(self):
        result = as_json({"key": "value"})
        assert json.loads(result) == {"key": "value"}

    def test_unicode(self):
        result = as_json({"text": "Привет мир"})
        assert "Привет" in result

    def test_nested(self):
        data = {"items": [1, 2, 3], "meta": {"count": 3}}
        result = as_json(data)
        assert json.loads(result) == data


class TestFlattenedKeywords:
    def test_returns_list(self):
        result = flattened_keywords()
        assert isinstance(result, list)
        assert len(result) > 0

    def test_all_lowercase(self):
        result = flattened_keywords()
        for phrase in result:
            assert phrase == phrase.lower()

    def test_no_empty_strings(self):
        result = flattened_keywords()
        for phrase in result:
            assert len(phrase) > 0

    def test_contains_known_phrases(self):
        result = flattened_keywords()
        result_text = " ".join(result)
        # These are in keywords.yaml
        assert "staking" in result_text
        assert "bot" in result_text


class TestLogRun:
    def test_inserts_row(self, db):
        log_run(db, "scan", source="hackernews", status="ok", inserted=10)
        row = db.execute("SELECT * FROM run_log").fetchone()
        assert row is not None
        assert row["command"] == "scan"
        assert row["source"] == "hackernews"
        assert row["status"] == "ok"
        assert row["rows_inserted"] == 10

    def test_defaults(self, db):
        log_run(db, "pipeline")
        row = db.execute("SELECT * FROM run_log").fetchone()
        assert row["status"] == "ok"
        assert row["rows_inserted"] == 0
        assert row["rows_updated"] == 0
