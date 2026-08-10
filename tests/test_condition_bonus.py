# ───────────────────────────────────────────────────────────────────
# Tests for the condition-grading score bonus
# ───────────────────────────────────────────────────────────────────
# price_analyzer.py's "Factor 2: Condition bonus" previously only
# recognized "new"/"certified"/"refurbished" (+5) and "open"/
# "excellent" (+3) -- the "Good"/"Fair" grading tiers used by
# Swappa/BackMarket/Gazelle-style condition grading (Excellent/Good/
# Fair) fell through with no bonus at all. These tests confirm:
#   1. "Good" condition now gets a small bonus.
#   2. "Fair" condition still gets no bonus (bottom of that scale,
#      same as plain "Used").
#   3. The existing New > Excellent > Good > Fair/Used ordering holds.
# ───────────────────────────────────────────────────────────────────

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import SearchConfig, PriceConfig
from database import Listing
from price_analyzer import PriceAnalyzer


class FakeConfig:
    def __init__(self, search: SearchConfig, price: PriceConfig):
        self.search = search
        self.price = price


def _search_config() -> SearchConfig:
    return SearchConfig(
        product_name="iPhone Pro Max",
        chip=None,
        chip_fallback=None,
        screen_sizes=[],
        ram_gb_primary=None,
        ram_gb_fallback=None,
        storage_gb_min=1000,
        storage_gb_max=None,
        results_per_size=20,
        location=None,
    )


def _price_config() -> PriceConfig:
    return PriceConfig(
        absolute_max_usd=5000,
        great_deal_usd={64: 900},
        good_deal_usd={64: 1100},
        top_deals_count=15,
    )


def _make_listing(condition, listing_id) -> Listing:
    return Listing(
        source="swappa",
        listing_id=listing_id,
        title="Apple iPhone 17 Pro Max 1TB Unlocked",
        price_usd=1000.0,
        url="https://swappa.com/x",
        condition=condition,
    )


def test_good_condition_gets_small_bonus():
    config = FakeConfig(_search_config(), _price_config())
    analyzer = PriceAnalyzer(config)

    listings = [
        _make_listing("Good", "good1"),
        _make_listing("Fair", "fair1"),
    ]
    analyzed = analyzer.analyze(listings)

    good = next(x for x in analyzed if x.listing_id == "good1")
    fair = next(x for x in analyzed if x.listing_id == "fair1")

    assert good.deal_score > fair.deal_score


def test_condition_ordering_new_excellent_good_fair():
    config = FakeConfig(_search_config(), _price_config())
    analyzer = PriceAnalyzer(config)

    listings = [
        _make_listing("Certified Pre-Owned", "new1"),
        _make_listing("Excellent", "excellent1"),
        _make_listing("Good", "good1"),
        _make_listing("Fair", "fair1"),
        _make_listing("Used", "used1"),
    ]
    analyzed = {x.listing_id: x for x in analyzer.analyze(listings)}

    assert analyzed["new1"].deal_score > analyzed["excellent1"].deal_score
    assert analyzed["excellent1"].deal_score > analyzed["good1"].deal_score
    assert analyzed["good1"].deal_score > analyzed["fair1"].deal_score
    # Fair is the bottom of the graded scale -- same as plain "Used".
    assert analyzed["fair1"].deal_score == analyzed["used1"].deal_score
