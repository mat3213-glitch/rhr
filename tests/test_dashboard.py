"""Tests for dashboard/build.py — build, _esc, _render."""
import json
import sqlite3

from dashboard.build import build, _esc, _render, DB_PATH, OUT


class TestEsc:
    def test_escapes_html(self):
        assert _esc("<b>") == "&lt;b&gt;"
        assert _esc('a&b') == "a&amp;b"
        assert _esc('"x"') == "&quot;x&quot;"

    def test_plain_text(self):
        assert _esc("hello world") == "hello world"


class TestRender:
    def test_empty_state(self):
        html = _render(empty=True)
        assert "No data yet" in html
        assert "<!DOCTYPE html>" in html

    def test_with_data(self):
        html = _render(
            empty=False,
            signals_total=100,
            signals_kept=80,
            signals_dup=15,
            signals_lq=5,
            candidates_total=10,
            stages={"L2-scored": 8, "L3-demand-check": 2},
            categories={"digital_asset": 5, "crypto_defi": 3},
            methods={"bot": 4, "micro_saas": 3},
            sources={"hackernews": 60, "rss": 40},
            top=[],
            runs=[],
            score_dist={"0.4-0.6": 5, "0.6-0.8": 3},
        )
        assert "100" in html
        assert "L2-scored" in html
        assert "digital_asset" in html
        assert "chart.js" in html.lower()


class TestBuild:
    def test_builds_with_real_db(self, tmp_path):
        import sqlite3
        from pathlib import Path
        schema_path = Path(__file__).parent.parent / "data" / "schema.sql"
        db_path = tmp_path / "test.db"
        conn = sqlite3.connect(db_path)
        conn.executescript(schema_path.read_text())
        conn.execute(
            "INSERT INTO candidates (title, category, method_type, passive_level, "
            "est_roi_band, risk_band, time_to_setup, score, funnel_stage) "
            "VALUES ('Test Bot', 'algo', 'ai_wrapper', 'hands_off', 'medium', 'low', 'day', 0.75, 'L2-scored')"
        )
        conn.commit()
        conn.close()
        html = build(db_path=db_path)
        assert "<!DOCTYPE html>" in html
        assert "Rabbit Hole Radar" in html
