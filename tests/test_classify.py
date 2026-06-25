"""Tests for pipeline/classify.py — rule_backend, helpers, classify_pending."""
import json

from pipeline.classify import (
    ClassifyInput,
    ClassifyOutput,
    _category_and_method,
    _fallback_title,
    _passive_level,
    _risk_band,
    _roi_band,
    _summary,
    _time_to_setup,
    _trend_velocity,
    _vibe_codability,
    rule_backend,
    classify_pending,
)


def _make_input(**overrides) -> ClassifyInput:
    defaults = dict(
        signal_id=1, source="hackernews", title="Test", body_text=None,
        url=None, points=None, matched_groups=[],
    )
    defaults.update(overrides)
    return ClassifyInput(**defaults)


# ── rule_backend ────────────────────────────────────────────────────────────

class TestRuleBackend:
    def test_no_matching_group_returns_none(self):
        inp = _make_input(matched_groups=[])
        assert rule_backend(inp) is None

    def test_unrelated_group_returns_none(self):
        inp = _make_input(matched_groups=["other_group"])
        assert rule_backend(inp) is None

    def test_money_making_group_classifies(self):
        inp = _make_input(
            title="How I make money with bots",
            matched_groups=["money_making"],
        )
        result = rule_backend(inp)
        assert result is not None
        assert result.is_opportunity is True
        # money_making alone falls through to ("other", "other")
        assert result.category == "other"
        assert result.method_type == "other"

    def test_crypto_staking(self):
        inp = _make_input(
            title="Best staking yields in DeFi",
            matched_groups=["crypto_defi"],
        )
        result = rule_backend(inp)
        assert result.category == "crypto_defi"
        assert result.method_type == "staking"

    def test_crypto_yield(self):
        inp = _make_input(
            title="Liquidity pool yield farming guide",
            matched_groups=["crypto_defi"],
        )
        result = rule_backend(inp)
        assert result.category == "crypto_defi"
        assert result.method_type == "yield"

    def test_crypto_airdrop(self):
        inp = _make_input(
            title="Upcoming airdrop opportunities",
            matched_groups=["crypto_defi"],
        )
        result = rule_backend(inp)
        assert result.category == "crypto_defi"
        assert result.method_type == "airdrop"

    def test_crypto_mev_becomes_algo(self):
        inp = _make_input(
            title="MEV trading bot strategy",
            matched_groups=["crypto_defi"],
        )
        result = rule_backend(inp)
        assert result.category == "algo"
        assert result.method_type == "trading_bot"

    def test_build_intent_bot(self):
        inp = _make_input(
            title="Building a Telegram bot for X",
            matched_groups=["build_intent"],
        )
        result = rule_backend(inp)
        assert result.category == "digital_asset"
        assert result.method_type == "bot"

    def test_build_intent_ai_wrapper(self):
        inp = _make_input(
            title="AI wrapper for customer support",
            matched_groups=["build_intent"],
        )
        result = rule_backend(inp)
        assert result.method_type == "ai_wrapper"

    def test_build_intent_micro_saas(self):
        invo = _make_input(
            title="Micro SaaS idea: invoice generator",
            matched_groups=["build_intent"],
        )
        result = rule_backend(invo)
        assert result.method_type == "micro_saas"

    def test_automation_scraper(self):
        inp = _make_input(
            title="Building a web scraper for prices",
            matched_groups=["automation"],
        )
        result = rule_backend(inp)
        assert result.category == "algo"
        assert result.method_type == "scraper"

    def test_automation_bot(self):
        inp = _make_input(
            title="Automation bot for social media",
            matched_groups=["automation"],
        )
        result = rule_backend(inp)
        assert result.method_type == "bot"

    def test_automation_plain(self):
        inp = _make_input(
            title="Automating data entry tasks",
            matched_groups=["automation"],
        )
        result = rule_backend(inp)
        assert result.category == "algo"
        assert result.method_type == "automation"

    def test_arbitrage_in_text(self):
        inp = _make_input(
            title="Best affiliate programs for passive income",
            matched_groups=["money_making"],
        )
        result = rule_backend(inp)
        assert result.category == "arbitrage"
        assert result.method_type == "affiliate"

    def test_affiliate_in_text(self):
        inp = _make_input(
            title="Best affiliate programs for 2026",
            matched_groups=["money_making"],
        )
        result = rule_backend(inp)
        assert result.category == "arbitrage"
        assert result.method_type == "affiliate"

    def test_passive_level_hands_off(self):
        inp = _make_input(
            title="Set and forget staking strategy",
            matched_groups=["crypto_defi"],
        )
        result = rule_backend(inp)
        assert result.passive_level == "hands_off"

    def test_passive_level_flip(self):
        inp = _make_input(
            title="Flipping domains for profit",
            matched_groups=["money_making"],
        )
        result = rule_backend(inp)
        assert result.passive_level == "flip"

    def test_passive_level_semi_passive_default(self):
        inp = _make_input(
            title="Building a micro saas product",
            matched_groups=["build_intent"],
        )
        result = rule_backend(inp)
        assert result.passive_level == "semi_passive"

    def test_title_truncated_to_140(self):
        long_title = "A" * 200
        inp = _make_input(title=long_title, matched_groups=["money_making"])
        result = rule_backend(inp)
        assert len(result.title) <= 140

    def test_summary_contains_method_type(self):
        inp = _make_input(
            title="Building a bot",
            body_text="Some description",
            matched_groups=["build_intent"],
        )
        result = rule_backend(inp)
        assert "[bot]" in result.summary


# ── helper functions ────────────────────────────────────────────────────────

class TestCategoryAndMethod:
    def test_crypto_staking(self):
        assert _category_and_method("staking rewards", {"crypto_defi"}) == ("crypto_defi", "staking")

    def test_crypto_restaking(self):
        assert _category_and_method("restaking on eigenlayer", {"crypto_defi"}) == ("crypto_defi", "staking")

    def test_crypto_yield(self):
        assert _category_and_method("yield farming apy", {"crypto_defi"}) == ("crypto_defi", "yield")

    def test_crypto_lp(self):
        assert _category_and_method("providing lp on uniswap", {"crypto_defi"}) == ("crypto_defi", "yield")

    def test_crypto_airdrop(self):
        assert _category_and_method("airdrop incoming", {"crypto_defi"}) == ("crypto_defi", "airdrop")

    def test_crypto_mev(self):
        assert _category_and_method("mev strategy", {"crypto_defi"}) == ("algo", "trading_bot")

    def test_crypto_fallback(self):
        assert _category_and_method("some crypto thing", {"crypto_defi"}) == ("crypto_defi", "other")

    def test_arbitrage_group(self):
        assert _category_and_method("arbitrage opp", {"arbitrage"}) == ("arbitrage", "affiliate")

    def test_affiliate_in_text(self):
        assert _category_and_method("best affiliate programs", {"money_making"}) == ("arbitrage", "affiliate")

    def test_dropship_in_text(self):
        assert _category_and_method("dropshipping guide", {"money_making"}) == ("arbitrage", "affiliate")

    def test_build_intent_bot(self):
        assert _category_and_method("building a bot", {"build_intent"}) == ("digital_asset", "bot")

    def test_build_intent_ai_wrapper(self):
        assert _category_and_method("gpt wrapper app", {"build_intent"}) == ("digital_asset", "ai_wrapper")

    def test_build_intent_micro_saas(self):
        assert _category_and_method("micro saas idea", {"build_intent"}) == ("digital_asset", "micro_saas")

    def test_build_intent_default(self):
        assert _category_and_method("building something", {"build_intent"}) == ("digital_asset", "micro_saas")

    def test_demand_gap_default(self):
        assert _category_and_method("need a tool for x", {"demand_gap"}) == ("digital_asset", "micro_saas")

    def test_automation_scraper(self):
        assert _category_and_method("web scraping tool", {"automation"}) == ("algo", "scraper")

    def test_automation_bot(self):
        assert _category_and_method("automation bot", {"automation"}) == ("digital_asset", "bot")

    def test_automation_default(self):
        assert _category_and_method("automating workflows", {"automation"}) == ("algo", "automation")

    def test_no_match(self):
        assert _category_and_method("random text", set()) == ("other", "other")


class TestPassiveLevel:
    def test_hands_off_staking(self):
        assert _passive_level("staking rewards", set()) == "hands_off"

    def test_hands_off_yield(self):
        assert _passive_level("yield farming", set()) == "hands_off"

    def test_hands_off_set_and_forget(self):
        assert _passive_level("set and forget strategy", set()) == "hands_off"

    def test_flip(self):
        assert _passive_level("flipping domains", set()) == "flip"

    def test_flip_arbitrage(self):
        assert _passive_level("arbitrage between exchanges", set()) == "flip"

    def test_semi_passive_default(self):
        assert _passive_level("building a product", set()) == "semi_passive"


class TestRoiBand:
    def test_crypto_high(self):
        assert _roi_band("anything", "crypto_defi", None) == "high"

    def test_algo_medium(self):
        assert _roi_band("anything", "algo", None) == "medium"

    def test_high_points_medium(self):
        assert _roi_band("anything", "digital_asset", 250) == "medium"

    def test_low_points_low(self):
        assert _roi_band("anything", "digital_asset", 50) == "low"

    def test_no_points_low(self):
        assert _roi_band("anything", "digital_asset", None) == "low"


class TestRiskBand:
    def test_crypto_yield_high(self):
        assert _risk_band("crypto_defi", "yield") == "high"

    def test_crypto_staking_high(self):
        assert _risk_band("crypto_defi", "staking") == "high"

    def test_crypto_airdrop_high(self):
        assert _risk_band("crypto_defi", "airdrop") == "high"

    def test_trading_bot_very_high(self):
        assert _risk_band("algo", "trading_bot") == "very_high"

    def test_micro_saas_low(self):
        assert _risk_band("digital_asset", "micro_saas") == "low"

    def test_ai_wrapper_low(self):
        assert _risk_band("digital_asset", "ai_wrapper") == "low"

    def test_bot_low(self):
        assert _risk_band("digital_asset", "bot") == "low"

    def test_arbitrage_medium(self):
        assert _risk_band("arbitrage", "affiliate") == "medium"

    def test_unknown_medium(self):
        assert _risk_band("other", "other") == "medium"


class TestTimeToSetup:
    def test_ai_wrapper(self):
        assert _time_to_setup("ai_wrapper") == "weekend"

    def test_micro_saas(self):
        assert _time_to_setup("micro_saas") == "weekend"

    def test_staking(self):
        assert _time_to_setup("staking") == "hours"

    def test_scraper(self):
        assert _time_to_setup("scraper") == "day"

    def test_unknown_defaults_to_week(self):
        assert _time_to_setup("unknown") == "week"


class TestVibeCodability:
    def test_ai_wrapper(self):
        assert _vibe_codability("", "ai_wrapper") == 0.9

    def test_bot(self):
        assert _vibe_codability("", "bot") == 0.9

    def test_scraper(self):
        assert _vibe_codability("", "scraper") == 0.9

    def test_micro_saas(self):
        assert _vibe_codability("", "micro_saas") == 0.85

    def test_automation(self):
        assert _vibe_codability("", "automation") == 0.8

    def test_content(self):
        assert _vibe_codability("", "content") == 0.6

    def test_staking(self):
        assert _vibe_codability("", "staking") == 0.3

    def test_unknown(self):
        assert _vibe_codability("", "other") == 0.4


class TestTrendVelocity:
    def test_zero_points(self):
        assert _trend_velocity(0, "hackernews") == 0.2

    def test_none_points(self):
        assert _trend_velocity(None, "hackernews") == 0.2

    def test_negative_points(self):
        assert _trend_velocity(-5, "hackernews") == 0.2

    def test_50_points(self):
        v = _trend_velocity(50, "hackernews")
        assert 0.8 < v < 0.95  # 0.2 + 0.13 * log10(50) * 3 ≈ 0.862

    def test_200_points(self):
        v = _trend_velocity(200, "hackernews")
        assert v >= 0.95  # 0.2 + 0.13 * log10(200) * 3 ≈ 1.097 → clamped to 1.0

    def test_1000_points(self):
        v = _trend_velocity(1000, "hackernews")
        assert v > 0.9

    def test_max_is_1(self):
        v = _trend_velocity(100000, "hackernews")
        assert v <= 1.0


class TestFallbackTitle:
    def test_short_text(self):
        assert _fallback_title("hello world") == "hello world"

    def test_long_text_truncated(self):
        long = "A" * 200
        assert len(_fallback_title(long)) <= 140

    def test_splits_on_dot(self):
        assert _fallback_title("Title. Rest of text") == "Title"

    def test_empty_returns_untitled(self):
        assert _fallback_title("") == "Untitled opportunity"


class TestSummary:
    def test_with_body(self):
        s = _summary("Title", "Body text here", "bot")
        assert s.startswith("[bot] ")
        assert "Title" in s
        assert "Body text here" in s

    def test_without_body(self):
        s = _summary("Title", None, "bot")
        assert s == "[bot] Title."

    def test_long_body_truncated(self):
        body = "word " * 100
        s = _summary("Title", body, "bot")
        assert "…" in s or len(s) < 300


# ── classify_pending (integration) ──────────────────────────────────────────

class TestClassifyPending:
    def _insert_signal(self, db, signal_id, groups, title="Test", l1_status="kept"):
        db.execute(
            """INSERT INTO signals (id, source, source_item_id, fetched_at, title, matched_groups, l1_status)
               VALUES (?, 'hackernews', ?, '2026-01-01T00:00:00Z', ?, ?, ?)""",
            (signal_id, f"item_{signal_id}", title, json.dumps(groups), l1_status),
        )
        db.commit()

    def test_creates_candidate(self, db):
        self._insert_signal(db, 1, ["money_making"], title="Making money with bots")
        result = classify_pending(db)
        assert result["candidates_created"] == 1
        assert result["signals_skipped"] == 0
        cand = db.execute("SELECT * FROM candidates").fetchone()
        assert cand is not None
        # money_making alone falls through to "other" category
        assert cand["category"] == "other"

    def test_skips_low_quality_signals(self, db):
        self._insert_signal(db, 1, [], l1_status="low_quality")
        result = classify_pending(db)
        assert result["candidates_created"] == 0

    def test_skips_already_linked_signals(self, db):
        self._insert_signal(db, 1, ["money_making"], title="Bot idea")
        # Create candidate and link
        cur = db.execute(
            "INSERT INTO candidates (title, funnel_stage) VALUES ('x', 'L2-scored')"
        )
        db.execute(
            "INSERT INTO candidate_signals (candidate_id, signal_id, weight) VALUES (?, 1, 1.0)",
            (cur.lastrowid,),
        )
        db.commit()
        result = classify_pending(db)
        assert result["candidates_created"] == 0

    def test_idempotent(self, db):
        self._insert_signal(db, 1, ["money_making"], title="Bot idea")
        classify_pending(db)
        result = classify_pending(db)
        assert result["candidates_created"] == 0
        assert result["signals_skipped"] == 0  # SQL already filters out linked signals
