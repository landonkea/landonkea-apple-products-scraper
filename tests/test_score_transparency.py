# ───────────────────────────────────────────────────────────────────
# Tests for score transparency, per-source reliability, and the
# "vs. Apple Refurb" baseline comparison
# ───────────────────────────────────────────────────────────────────
# Three related additions to PriceAnalyzer, all covered here:
#   1. format_score_breakdown() — renders a deal_score_breakdown dict
#      into a compact, human-readable string.
#   2. _score_listing() attaches a `deal_score_breakdown` to every
#      listing whose named components sum to the final score.
#   3. Per-source reliability nudge — DEFAULT_SOURCE_RELIABILITY_BONUS
#      plus config.yaml's price.source_reliability override.
#   4. "vs. Apple Refurb" baseline — a listing cheaper than Apple
#      Refurb's price for the exact same (chip, ram_gb, storage_gb)
#      gets apple_refurb_price/vs_apple_refurb_pct set.
# ───────────────────────────────────────────────────────────────────

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import SearchConfig, PriceConfig
from database import Listing
from price_analyzer import PriceAnalyzer, format_score_breakdown


class FakeConfig:
    def __init__(self, search: SearchConfig, price: PriceConfig):
        self.search = search
        self.price = price


def _make_search_config(**overrides) -> SearchConfig:
    defaults = dict(
        product_name="MacBook Pro",
        chip=None,
        chip_fallback=None,
        screen_sizes=[],
        ram_gb_primary=128,
        ram_gb_fallback=64,
        storage_gb_min=1024,
        storage_gb_max=None,
        results_per_size=20,
        location=None,
    )
    defaults.update(overrides)
    return SearchConfig(**defaults)


def _make_price_config(**overrides) -> PriceConfig:
    defaults = dict(
        absolute_max_usd=8000,
        great_deal_usd={128: 5000, 64: 4000},
        good_deal_usd={128: 5500, 64: 4500},
        top_deals_count=40,
    )
    defaults.update(overrides)
    return PriceConfig(**defaults)


def _make_analyzer(**price_overrides) -> PriceAnalyzer:
    config = FakeConfig(_make_search_config(), _make_price_config(**price_overrides))
    return PriceAnalyzer(config)


def _make_listing(source, price_usd, listing_id=None, condition=None,
                   chip="M5 Max", ram_gb=128, storage_gb=1024) -> Listing:
    return Listing(
        source=source,
        listing_id=listing_id or f"id_{source}_{price_usd}",
        title=f"MacBook Pro 14 {chip} {ram_gb}GB",
        price_usd=price_usd,
        url=f"https://{source}.com/itm/{listing_id or price_usd}",
        condition=condition,
        chip=chip,
        ram_gb=ram_gb,
        storage_gb=storage_gb,
    )


# ── format_score_breakdown() ───────────────────────────────────────

def test_format_score_breakdown_empty_or_none_returns_empty_string():
    assert format_score_breakdown(None) == ""
    assert format_score_breakdown({}) == ""


def test_format_score_breakdown_renders_absolute_and_signed_components():
    breakdown = {"base": 50.0, "price_vs_median": 18.2, "condition": 5.0,
                 "source_reliability": -3.0}
    rendered = format_score_breakdown(breakdown)

    assert rendered == "base 50 | price +18.2 | condition +5.0 | source -3.0"


def test_format_score_breakdown_normalizes_negative_zero():
    # A component that nets to exactly 0.0 after being negative
    # elsewhere shouldn't render as the ugly "+-0.0".
    breakdown = {"spec_bonus": -0.0}
    assert format_score_breakdown(breakdown) == "specs +0.0"


# ── _score_listing() attaches a coherent breakdown ─────────────────

def test_score_listing_breakdown_sums_to_prescore_and_has_expected_keys():
    analyzer = _make_analyzer()
    listings = [
        _make_listing("ebay", 4000.0, condition="New"),
        _make_listing("ebay", 4500.0, condition="Used"),
        _make_listing("ebay", 5000.0, condition="Used"),
    ]

    analyzed = analyzer.analyze(listings)
    listing = analyzed[0]

    breakdown = listing.deal_score_breakdown
    assert breakdown is not None
    assert set(breakdown.keys()) >= {"base", "price_vs_median", "condition",
                                      "source_reliability", "spec_bonus"}

    # Components (pre-clamp/cap) should sum to the listing's score,
    # modulo any clamp/cap adjustment explicitly recorded.
    total = sum(breakdown.values())
    assert round(total, 1) == listing.deal_score


def test_score_listing_no_batch_data_uses_baseline_breakdown():
    # This branch only fires when _score_listing() is called with no
    # listings in the batch at all (stats["count"] == 0) -- calling it
    # directly (rather than through analyze(), which always adds the
    # listing to the batch first) is the only way to exercise it.
    analyzer = _make_analyzer()
    listing = _make_listing("ebay", 3900.0)  # below great_deal_usd[128]=5000

    score = analyzer._score_listing(listing)

    assert listing.deal_score_breakdown == {"no_batch_data_baseline": 90.0}
    assert score == 90.0


# ── Per-source reliability ──────────────────────────────────────────

def test_source_reliability_bonus_uses_defaults():
    analyzer = _make_analyzer()

    assert analyzer._source_reliability_bonus("apple_refurb") == 2.0
    assert analyzer._source_reliability_bonus("craigslist") == -3.0
    assert analyzer._source_reliability_bonus("ebay") == 0.0
    # Unknown source -> neutral, never penalized by omission.
    assert analyzer._source_reliability_bonus("some_new_scraper") == 0.0


def test_source_reliability_config_override_takes_precedence():
    analyzer = _make_analyzer(source_reliability={"offerup": -5})

    assert analyzer._source_reliability_bonus("offerup") == -5.0
    # Untouched sources keep their built-in default.
    assert analyzer._source_reliability_bonus("craigslist") == -3.0


def test_same_priced_listings_on_different_sources_get_different_scores():
    # A more reliable source should never score LOWER than a less
    # reliable one at the identical price -- the whole point of the
    # nudge.
    analyzer = _make_analyzer()
    listings = [
        _make_listing("craigslist", 4500.0, listing_id="cl1", condition="Used"),
        _make_listing("apple_refurb", 4500.0, listing_id="ar1", condition="Used"),
        _make_listing("ebay", 5000.0, listing_id="eb1", condition="Used"),  # pulls median up
    ]

    analyzed = analyzer.analyze(listings)
    by_id = {ln.listing_id: ln for ln in analyzed}

    assert by_id["ar1"].deal_score > by_id["cl1"].deal_score


# ── "vs. Apple Refurb" baseline ─────────────────────────────────────

def test_listing_cheaper_than_apple_refurb_gets_baseline_fields():
    analyzer = _make_analyzer()
    listings = [
        _make_listing("apple_refurb", 5000.0, listing_id="ar1"),
        _make_listing("ebay", 3000.0, listing_id="eb1"),
    ]

    analyzed = analyzer.analyze(listings)
    by_id = {ln.listing_id: ln for ln in analyzed}

    ebay_listing = by_id["eb1"]
    assert ebay_listing.apple_refurb_price == 5000.0
    assert ebay_listing.vs_apple_refurb_pct == 40.0


def test_apple_refurb_listing_never_gets_baseline_against_itself():
    analyzer = _make_analyzer()
    listings = [
        _make_listing("apple_refurb", 5000.0, listing_id="ar1"),
        _make_listing("apple_refurb", 4800.0, listing_id="ar2"),
    ]

    analyzed = analyzer.analyze(listings)

    for listing in analyzed:
        assert listing.apple_refurb_price is None
        assert listing.vs_apple_refurb_pct is None


def test_listing_more_expensive_than_apple_refurb_gets_no_baseline():
    analyzer = _make_analyzer()
    listings = [
        _make_listing("apple_refurb", 4000.0, listing_id="ar1"),
        _make_listing("ebay", 4500.0, listing_id="eb1"),
    ]

    analyzed = analyzer.analyze(listings)
    by_id = {ln.listing_id: ln for ln in analyzed}

    assert by_id["eb1"].apple_refurb_price is None


def test_baseline_only_matches_same_configuration():
    analyzer = _make_analyzer()
    listings = [
        _make_listing("apple_refurb", 5000.0, listing_id="ar1",
                       chip="M5 Max", ram_gb=128, storage_gb=2048),
        # Different storage -> not the same config, no comparison.
        _make_listing("ebay", 3000.0, listing_id="eb1",
                       chip="M5 Max", ram_gb=128, storage_gb=1024),
    ]

    analyzed = analyzer.analyze(listings)
    by_id = {ln.listing_id: ln for ln in analyzed}

    assert by_id["eb1"].apple_refurb_price is None


def test_baseline_uses_lowest_apple_refurb_price_for_config():
    analyzer = _make_analyzer()
    listings = [
        _make_listing("apple_refurb", 5200.0, listing_id="ar1"),
        _make_listing("apple_refurb", 4900.0, listing_id="ar2"),
        _make_listing("ebay", 3000.0, listing_id="eb1"),
    ]

    analyzed = analyzer.analyze(listings)
    by_id = {ln.listing_id: ln for ln in analyzed}

    assert by_id["eb1"].apple_refurb_price == 4900.0
