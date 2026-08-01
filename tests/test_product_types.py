# ───────────────────────────────────────────────────────────────────
# Tests for the product_type registry and dispatch (src/product_types/)
# ───────────────────────────────────────────────────────────────────
# These confirm the plumbing works: PRODUCT_TYPES resolves
# "electronics" to a real ElectronicsHandler, BaseScraper's
# parse_common_specs()/passes_filters() correctly delegate to it, and
# PriceAnalyzer's scoring delegates its product-specific bonuses too.
# The underlying electronics logic itself (chip/RAM regex parsing,
# accessory filtering, etc.) is already covered by test_scrapers.py
# and test_price_analyzer.py — these tests are about the DISPATCH,
# not re-testing that logic.
#
# HOW TO RUN:
#   pytest tests/test_product_types.py -v
# ───────────────────────────────────────────────────────────────────

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import SearchConfig
from database import Listing
from product_types import PRODUCT_TYPES
from product_types.electronics import ElectronicsHandler, MINIMUM_PRICE_USD, MINIMUM_IPHONE_PRICE_USD
from scrapers.base import BaseScraper, ScrapedListing


def _make_search_config(**overrides) -> SearchConfig:
    defaults = dict(
        product_name="MacBook Pro",
        chip=None,
        chip_fallback=None,
        screen_sizes=[],
        ram_gb_primary=None,
        ram_gb_fallback=None,
        storage_gb_min=None,
        storage_gb_max=None,
        results_per_size=20,
        location=None,
    )
    defaults.update(overrides)
    return SearchConfig(**defaults)


class FakeScraper(BaseScraper):
    """Minimal concrete BaseScraper subclass — scrape() is abstract
    and unused by these tests, so it's stubbed out."""

    def scrape(self):
        return []


def _make_fake_config(search: SearchConfig):
    return SimpleNamespace(search=search, price=SimpleNamespace(absolute_max_usd=8000))


# ── Registry ─────────────────────────────────────────────────────────

def test_registry_has_electronics_handler():
    assert "electronics" in PRODUCT_TYPES
    assert isinstance(PRODUCT_TYPES["electronics"], ElectronicsHandler)


def test_search_config_defaults_to_electronics_product_type():
    search = _make_search_config()
    assert search.product_type == "electronics"


def test_search_config_accepts_explicit_product_type():
    search = _make_search_config(product_type="apparel")
    assert search.product_type == "apparel"


# ── BaseScraper.parse_common_specs() dispatch ───────────────────────

def test_parse_common_specs_dispatches_to_electronics_handler():
    search = _make_search_config()
    scraper = FakeScraper(_make_fake_config(search))
    specs = scraper.parse_common_specs(
        "Apple MacBook Pro 14-inch M5 Max chip 128GB Memory 2TB SSD"
    )
    assert specs["chip"] == "M5 Max"
    assert specs["ram_gb"] == 128
    assert specs["storage_gb"] == 2048
    assert specs["screen_size"] == 14.0


# ── BaseScraper.passes_filters() dispatch ───────────────────────────

def _make_listing(**overrides) -> ScrapedListing:
    defaults = dict(
        source="test", listing_id="1", title="Apple MacBook Pro 14-inch M5 Max chip 128GB Memory 1TB SSD",
        price_usd=3000.0, url="http://example.com", condition="Used",
        ram_gb=128, storage_gb=1024, screen_size=14.0, chip="M5 Max", location=None,
    )
    defaults.update(overrides)
    return ScrapedListing(**defaults)


def test_passes_filters_rejects_accessory_via_electronics_handler():
    search = _make_search_config()
    scraper = FakeScraper(_make_fake_config(search))
    listing = _make_listing(title="MacBook Pro 14-inch Hard Shell Case")
    assert scraper.passes_filters(listing) is False


def test_passes_filters_rejects_wrong_chip():
    search = _make_search_config(chip="M5 Max")
    scraper = FakeScraper(_make_fake_config(search))
    listing = _make_listing(chip="M3 Pro")
    assert scraper.passes_filters(listing) is False


def test_passes_filters_accepts_matching_listing():
    search = _make_search_config(chip="M5 Max")
    scraper = FakeScraper(_make_fake_config(search))
    listing = _make_listing()
    assert scraper.passes_filters(listing) is True


def test_passes_filters_uses_iphone_min_price_for_iphone_search():
    search = _make_search_config(product_name="iPhone Pro Max", storage_gb_min=1000)
    scraper = FakeScraper(_make_fake_config(search))
    listing = _make_listing(
        title="Apple iPhone 16 Pro Max 1TB Unlocked",
        price_usd=150.0,  # above the $100 iPhone floor, below the $200 electronics floor
        chip=None, ram_gb=None, storage_gb=1024, screen_size=None,
    )
    assert scraper.passes_filters(listing) is True


def test_passes_filters_rejects_below_iphone_min_price():
    search = _make_search_config(product_name="iPhone Pro Max", storage_gb_min=1000)
    scraper = FakeScraper(_make_fake_config(search))
    listing = _make_listing(
        title="Apple iPhone 16 Pro Max 1TB Unlocked",
        price_usd=50.0,  # below the $100 iPhone floor
        chip=None, ram_gb=None, storage_gb=1024, screen_size=None,
    )
    assert scraper.passes_filters(listing) is False


# ── ElectronicsHandler.min_price_usd() ──────────────────────────────

def test_min_price_usd_iphone_vs_macbook():
    handler = ElectronicsHandler()
    assert handler.min_price_usd(_make_search_config(product_name="iPhone Pro Max")) == MINIMUM_IPHONE_PRICE_USD
    assert handler.min_price_usd(_make_search_config(product_name="MacBook Pro")) == MINIMUM_PRICE_USD


# ── ElectronicsHandler.score_bonuses() ──────────────────────────────

def test_score_bonuses_rewards_primary_ram():
    handler = ElectronicsHandler()
    search = _make_search_config(ram_gb_primary=128, ram_gb_fallback=64)
    listing = Listing(source="t", listing_id="1", title="t", price_usd=100, url="u", ram_gb=128)
    bonus_128 = handler.score_bonuses(listing, search)
    listing.ram_gb = 64
    bonus_64 = handler.score_bonuses(listing, search)
    assert bonus_128 > bonus_64


def test_score_bonuses_prefers_newest_chip_generation():
    handler = ElectronicsHandler()
    search = _make_search_config(chip_generation_map={"M5 Max": 5, "M4 Max": 4, "M3 Max": 3})
    newest = Listing(source="t", listing_id="1", title="t", price_usd=100, url="u", chip="M5 Max")
    oldest = Listing(source="t", listing_id="2", title="t", price_usd=100, url="u", chip="M3 Max")
    assert handler.score_bonuses(newest, search) > handler.score_bonuses(oldest, search)
