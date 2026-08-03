"""youtube_ytdlp collector — parsing, caps, dedup and the silent-ban diagnostic.

The collector shells out to yt-dlp, so every test replaces subprocess.run with a
stub. What matters here is that garbage lines never crash a run and that an
IP ban (rc!=0, empty stdout) is reported instead of looking like "found nothing".
"""
from __future__ import annotations

import json
import subprocess

import pytest

from collectors.youtube_ytdlp import YouTubeYtDlpCollector


class _Proc:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout, self.stderr, self.returncode = stdout, stderr, returncode


def _lines(*rows) -> str:
    out = []
    for r in rows:
        out.append(json.dumps(r) if isinstance(r, dict) else r)
    return "\n".join(out)


@pytest.fixture
def stub(monkeypatch):
    """Patch shutil.which + subprocess.run; returns a setter for the fake stdout."""
    monkeypatch.setattr("collectors.youtube_ytdlp.shutil.which", lambda _b: "/usr/bin/yt-dlp")
    box: dict[str, _Proc] = {"proc": _Proc()}

    def fake_run(cmd, **kwargs):
        return box["proc"]

    monkeypatch.setattr("collectors.youtube_ytdlp.subprocess.run", fake_run)
    return box


def test_parses_and_maps_fields(stub):
    stub["proc"] = _Proc(_lines({
        "id": "v1", "title": "T1", "description": "d1", "uploader": "u1",
        "view_count": 10, "comment_count": 2, "timestamp": 1780000000,
    }))
    items = YouTubeYtDlpCollector({"search_terms": ["t"]}).fetch()
    assert len(items) == 1
    it = items[0]
    assert (it.source, it.source_item_id, it.author, it.points) == ("youtube_ytdlp", "v1", "u1", 10)
    assert it.url == "https://www.youtube.com/watch?v=v1"
    assert it.published_at and it.published_at.endswith("Z")
    assert it.matched_groups == ["t"]


def test_skips_broken_lines_and_entries_without_id(stub):
    stub["proc"] = _Proc(_lines("NOT JSON", {"title": "no id"}, {"id": "ok1", "title": "T"}))
    items = YouTubeYtDlpCollector({"search_terms": ["t"]}).fetch()
    assert [i.source_item_id for i in items] == ["ok1"]


def test_dedup_and_cap(stub):
    stub["proc"] = _Proc(_lines(
        {"id": "a"}, {"id": "a"}, {"id": "b"}, {"id": "c"},
    ))
    items = YouTubeYtDlpCollector({"search_terms": ["t"], "max_results_per_term": 2}).fetch()
    assert [i.source_item_id for i in items] == ["a", "b"]


def test_ban_is_reported_not_silent(stub, capsys):
    """rc!=0 with empty stdout is an IP ban — it must not look like an empty result."""
    stub["proc"] = _Proc("", "ERROR: Sign in to confirm you're not a bot", returncode=1)
    items = YouTubeYtDlpCollector({"search_terms": ["t"]}).fetch()
    assert items == []
    assert "Sign in to confirm" in capsys.readouterr().out


def test_timeout_does_not_kill_the_run(monkeypatch, capsys):
    monkeypatch.setattr("collectors.youtube_ytdlp.shutil.which", lambda _b: "/usr/bin/yt-dlp")

    def boom(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr("collectors.youtube_ytdlp.subprocess.run", boom)
    assert YouTubeYtDlpCollector({"search_terms": ["t"]}).fetch() == []
    assert "Timeout" in capsys.readouterr().out


def test_missing_binary_returns_empty(monkeypatch, capsys):
    monkeypatch.setattr("collectors.youtube_ytdlp.shutil.which", lambda _b: None)
    assert YouTubeYtDlpCollector({"search_terms": ["t"]}).fetch() == []
    assert "pip install yt-dlp" in capsys.readouterr().out
