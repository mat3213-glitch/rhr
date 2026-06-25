"""Tests for pipeline/dedup.py — dedup_key_for, _url_key, _norm_text, dedup_signals."""
from models import RawItem
from pipeline.dedup import _norm_text, _url_key, dedup_key_for, dedup_signals


class TestUrlKey:
    def test_normal_url(self):
        assert _url_key("https://example.com/post") == "u:example.com/post"

    def test_strips_www(self):
        assert _url_key("https://www.example.com/post") == "u:example.com/post"

    def test_strips_index_html(self):
        assert _url_key("https://example.com/page/index.html") == "u:example.com/page"

    def test_strips_trailing_slash(self):
        assert _url_key("https://example.com/post/") == "u:example.com/post"

    def test_no_netloc(self):
        assert _url_key("not-a-url") is None

    def test_empty_string(self):
        assert _url_key("") is None

    def test_preserves_path(self):
        assert _url_key("https://blog.example.com/2026/01/post") == "u:blog.example.com/2026/01/post"


class TestNormText:
    def test_lowercase(self):
        assert _norm_text("HELLO World") == "hello world"

    def test_strips_punctuation(self):
        # NOPUNCT replaces with spaces, no final strip → trailing space possible
        result = _norm_text("hello, world!")
        assert result.startswith("hello world")
        assert "," not in result
        assert "!" not in result

    def test_collapses_whitespace(self):
        assert _norm_text("  hello   world  ") == "hello world"

    def test_truncates_at_200(self):
        long = "a" * 300
        assert len(_norm_text(long)) == 200

    def test_empty_string(self):
        assert _norm_text("") == ""


class TestDedupKeyFor:
    def test_with_url(self):
        item = RawItem(source="rss", source_item_id="1", url="https://example.com/post")
        key = dedup_key_for(item)
        assert isinstance(key, str)
        assert len(key) == 32  # md5 hex

    def test_same_url_same_key(self):
        item1 = RawItem(source="rss", source_item_id="1", url="https://example.com/post")
        item2 = RawItem(source="rss", source_item_id="2", url="https://example.com/post")
        assert dedup_key_for(item1) == dedup_key_for(item2)

    def test_different_urls_different_keys(self):
        item1 = RawItem(source="rss", source_item_id="1", url="https://example.com/a")
        item2 = RawItem(source="rss", source_item_id="2", url="https://example.com/b")
        assert dedup_key_for(item1) != dedup_key_for(item2)

    def test_title_fallback(self):
        item = RawItem(source="rss", source_item_id="1", title="Same Story")
        key = dedup_key_for(item)
        assert isinstance(key, str)
        assert len(key) == 32

    def test_same_title_same_key(self):
        item1 = RawItem(source="rss", source_item_id="1", title="Same Story")
        item2 = RawItem(source="rss", source_item_id="2", title="Same Story")
        assert dedup_key_for(item1) == dedup_key_for(item2)

    def test_body_fallback(self):
        item = RawItem(source="rss", source_item_id="1", body_text="Some body text")
        key = dedup_key_for(item)
        assert isinstance(key, str)
        assert len(key) == 32

    def test_url_takes_precedence(self):
        item = RawItem(
            source="rss", source_item_id="1",
            url="https://example.com/post",
            title="Different Title",
        )
        key = dedup_key_for(item)
        # Should match URL-based key, not title-based
        url_item = RawItem(source="rss", source_item_id="2", url="https://example.com/post")
        assert dedup_key_for(url_item) == key


class TestDedupSignals:
    def test_no_duplicates(self, db):
        db.execute(
            "INSERT INTO signals (source, source_item_id, fetched_at, dedup_key, l1_status) "
            "VALUES ('rss', '1', '2026-01-01T00:00:00Z', 'key1', 'kept')"
        )
        db.execute(
            "INSERT INTO signals (source, source_item_id, fetched_at, dedup_key, l1_status) "
            "VALUES ('rss', '2', '2026-01-01T00:00:00Z', 'key2', 'kept')"
        )
        db.commit()
        assert dedup_signals(db) == 0

    def test_marks_duplicates(self, db):
        db.execute(
            "INSERT INTO signals (source, source_item_id, fetched_at, dedup_key, l1_status) "
            "VALUES ('rss', '1', '2026-01-01T00:00:00Z', 'key1', 'kept')"
        )
        db.execute(
            "INSERT INTO signals (source, source_item_id, fetched_at, dedup_key, l1_status) "
            "VALUES ('rss', '2', '2026-01-02T00:00:00Z', 'key1', 'kept')"
        )
        db.commit()
        marked = dedup_signals(db)
        assert marked == 1
        row = db.execute("SELECT l1_status, is_duplicate_of FROM signals WHERE id=2").fetchone()
        assert row["l1_status"] == "duplicate"
        assert row["is_duplicate_of"] == 1

    def test_keeps_earliest_as_canonical(self, db):
        db.execute(
            "INSERT INTO signals (source, source_item_id, fetched_at, dedup_key, l1_status) "
            "VALUES ('rss', '1', '2026-01-03T00:00:00Z', 'key1', 'kept')"
        )
        db.execute(
            "INSERT INTO signals (source, source_item_id, fetched_at, dedup_key, l1_status) "
            "VALUES ('rss', '2', '2026-01-01T00:00:00Z', 'key1', 'kept')"
        )
        db.commit()
        dedup_signals(db)
        # Earlier one (id=2) should be canonical
        row1 = db.execute("SELECT l1_status FROM signals WHERE id=1").fetchone()
        row2 = db.execute("SELECT l1_status FROM signals WHERE id=2").fetchone()
        assert row1["l1_status"] == "duplicate"
        assert row2["l1_status"] == "kept"

    def test_only_processes_kept_signals(self, db):
        db.execute(
            "INSERT INTO signals (source, source_item_id, fetched_at, dedup_key, l1_status) "
            "VALUES ('rss', '1', '2026-01-01T00:00:00Z', 'key1', 'duplicate')"
        )
        db.execute(
            "INSERT INTO signals (source, source_item_id, fetched_at, dedup_key, l1_status) "
            "VALUES ('rss', '2', '2026-01-02T00:00:00Z', 'key1', 'duplicate')"
        )
        db.commit()
        assert dedup_signals(db) == 0
