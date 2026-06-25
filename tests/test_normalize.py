"""Tests for pipeline/normalize.py — normalize_and_store, _haystack, _match_groups."""
import json

from models import RawItem
from pipeline.normalize import _haystack, _match_groups, normalize_and_store


class TestHaystack:
    def test_title_and_body(self):
        item = RawItem(source="rss", source_item_id="1", title="Title", body_text="Body")
        assert _haystack(item) == "title body"

    def test_title_only(self):
        item = RawItem(source="rss", source_item_id="1", title="Title")
        # _haystack joins with space, so trailing space when body is None
        assert _haystack(item).strip() == "title"

    def test_body_only(self):
        item = RawItem(source="rss", source_item_id="1", body_text="Body")
        assert _haystack(item).strip() == "body"

    def test_neither(self):
        item = RawItem(source="rss", source_item_id="1")
        assert _haystack(item).strip() == ""


class TestMatchGroups:
    def test_matches_money_making(self):
        groups = _match_groups("how to make money online")
        assert "money_making" in groups

    def test_matches_build_intent(self):
        groups = _match_groups("building a micro saas")
        assert "build_intent" in groups

    def test_matches_crypto_defi(self):
        groups = _match_groups("best staking yields")
        assert "crypto_defi" in groups

    def test_no_match(self):
        groups = _match_groups("the weather is nice today")
        assert groups == []

    def test_multiple_groups(self):
        groups = _match_groups("passive income with crypto staking bot")
        assert "money_making" in groups  # "passive income"
        assert "crypto_defi" in groups   # "staking"
        assert "automation" in groups    # "bot"


class TestNormalizeAndStore:
    def _make_item(self, **overrides):
        # Use "passive income" which is an exact trigger phrase in money_making group
        defaults = dict(source="rss", source_item_id="item1", title="passive income ideas")
        defaults.update(overrides)
        return RawItem(**defaults)

    def test_inserts_matching_item(self, db):
        item = self._make_item()
        result = normalize_and_store(db, [item])
        assert result["inserted"] == 1
        assert result["dropped_l0"] == 0
        row = db.execute("SELECT * FROM signals").fetchone()
        assert row is not None
        assert row["source"] == "rss"
        assert row["l1_status"] == "kept"

    def test_drops_non_matching_item(self, db):
        item = self._make_item(title="The weather is nice")
        result = normalize_and_store(db, [item])
        assert result["inserted"] == 0
        assert result["dropped_l0"] == 1

    def test_skips_duplicate_source_item(self, db):
        item = self._make_item()
        normalize_and_store(db, [item])
        result = normalize_and_store(db, [item])
        assert result["skipped_existing"] == 1
        assert result["inserted"] == 0

    def test_multiple_items(self, db):
        items = [
            self._make_item(source_item_id="1", title="passive income ideas"),
            self._make_item(source_item_id="2", title="micro saas product"),
            self._make_item(source_item_id="3", title="the weather is nice"),
        ]
        result = normalize_and_store(db, items)
        assert result["inserted"] == 2
        assert result["dropped_l0"] == 1

    def test_stores_dedup_key(self, db):
        item = self._make_item(url="https://example.com/post")
        normalize_and_store(db, [item])
        row = db.execute("SELECT dedup_key FROM signals").fetchone()
        assert row["dedup_key"] is not None
        assert len(row["dedup_key"]) == 32  # md5 hex

    def test_stores_matched_groups_as_json(self, db):
        item = self._make_item(title="passive income ideas")
        normalize_and_store(db, [item])
        row = db.execute("SELECT matched_groups FROM signals").fetchone()
        groups = json.loads(row["matched_groups"])
        assert "money_making" in groups

    def test_empty_list(self, db):
        result = normalize_and_store(db, [])
        assert result == {"inserted": 0, "skipped_existing": 0, "dropped_l0": 0}
