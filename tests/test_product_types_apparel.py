# ───────────────────────────────────────────────────────────────────
# Tests for the apparel product type (src/product_types/apparel.py)
# ───────────────────────────────────────────────────────────────────
# This is the "second product_type" LARGE-tier feature: proof that
# the ProductTypeHandler interface (src/product_types/base.py) really
# does generalize to a category with a completely different field set
# (size/brand/color instead of chip/RAM/storage), not just electronics
# with different constants.
#
# Three layers of proof, mirroring test_product_types.py's structure:
#   1. Unit tests on ApparelHandler directly (parsing, filtering,
#      scoring, price floor).
#   2. Dispatch tests through BaseScraper (parse_common_specs/
#      passes_filters) with product_type="apparel" -- confirms the
#      scraper layer needs zero apparel-specific code, exactly as
#      base.py's module docstring promises.
#   3. get_enabled_scrapers() integration test -- confirms an apparel
#      search automatically includes the general marketplaces and
#      automatically skips the Apple-only storefronts, with no code
#      change to either.
#
# HOW TO RUN:
#   pytest tests/test_product_types_apparel.py -v
# ───────────────────────────────────────────────────────────────────

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import Config, SearchConfig, SiteConfig, SitesConfig
from database import Listing
from product_types import PRODUCT_TYPES
from product_types.apparel import ApparelHandler, MINIMUM_PRICE_USD, extract_size, extract_brand, extract_color
from scrapers.base import BaseScraper, ScrapedListing


def _make_search_config(**overrides) -> SearchConfig:
    defaults = dict(
        product_name="Red Wing Iron Ranger",
        chip=None,
        chip_fallback=None,
        screen_sizes=[],
        ram_gb_primary=None,
        ram_gb_fallback=None,
        storage_gb_min=None,
        storage_gb_max=None,
        results_per_size=20,
        location=None,
        product_type="apparel",
    )
    defaults.update(overrides)
    return SearchConfig(**defaults)


class FakeScraper(BaseScraper):
    """Minimal concrete BaseScraper subclass — scrape() is abstract
    and unused by these tests, so it's stubbed out."""

    def scrape(self):
        return []


def _make_fake_config(search: SearchConfig):
    return SimpleNamespace(search=search, price=SimpleNamespace(absolute_max_usd=1000))


def _make_listing(**overrides) -> ScrapedListing:
    defaults = dict(
        source="test", listing_id="1", title="Red Wing Iron Ranger Size 10.5 Black Boots",
        price_usd=250.0, url="http://example.com", condition="Used",
        ram_gb=None, storage_gb=None, screen_size=None, chip=None, location=None,
        size=10.5, brand="Red Wing", color="black",
    )
    defaults.update(overrides)
    return ScrapedListing(**defaults)


# ── Registry ─────────────────────────────────────────────────────────

def test_registry_has_apparel_handler():
    assert "apparel" in PRODUCT_TYPES
    assert isinstance(PRODUCT_TYPES["apparel"], ApparelHandler)


# ── Spec parsing ────────────────────────────────────────────────────

def test_extract_size_finds_half_size():
    assert extract_size("Red Wing Iron Ranger Size 10.5 Black") == 10.5


def test_extract_size_finds_sz_abbreviation():
    assert extract_size("Wolverine 1000 Mile Boots sz 9 Brown") == 9.0


def test_extract_size_returns_none_when_absent():
    assert extract_size("Red Wing Iron Ranger Boots Black") is None


def test_extract_size_ignores_implausible_values():
    # "size 42" isn't a real US boot size (looks like a EU size or
    # unrelated number) -- extract_size should not return it.
    assert extract_size("European size 42 boots") is None


def test_extract_brand_finds_known_brand():
    assert extract_brand("Wolverine 1000 Mile Boots Size 10") == "Wolverine"


def test_extract_brand_returns_none_for_unknown_brand():
    assert extract_brand("Generic Boots Size 10") is None


def test_extract_color_finds_known_color():
    assert extract_color("Red Wing Iron Ranger Oxblood Size 10.5") == "oxblood"


def test_parse_specs_returns_all_three_fields():
    handler = ApparelHandler()
    specs = handler.parse_specs("Red Wing Iron Ranger Size 10.5 Oxblood")
    assert specs == {"size": 10.5, "brand": "Red Wing", "color": "oxblood"}


# ── is_relevant() ───────────────────────────────────────────────────

def test_is_relevant_rejects_laces_only_listing():
    handler = ApparelHandler()
    search = _make_search_config()
    assert handler.is_relevant("Red Wing Boot Laces Only 72 inch", search) is False


def test_is_relevant_rejects_shoe_trees():
    handler = ApparelHandler()
    search = _make_search_config()
    assert handler.is_relevant("Cedar Shoe Trees for Red Wing Boots", search) is False


def test_is_relevant_rejects_bad_condition_in_condition_label():
    handler = ApparelHandler()
    search = _make_search_config()
    assert handler.is_relevant("Red Wing Iron Ranger Size 10.5", search, condition="As-Is") is False


def test_is_relevant_accepts_real_listing():
    handler = ApparelHandler()
    search = _make_search_config()
    assert handler.is_relevant("Red Wing Iron Ranger Size 10.5 Black Boots", search) is True


# ── passes_type_filters() ───────────────────────────────────────────

def test_passes_type_filters_rejects_wrong_size():
    handler = ApparelHandler()
    search = _make_search_config(sizes=[10, 10.5, 11])
    listing = Listing(source="t", listing_id="1", title="t", price_usd=250, url="u", size=9.0)
    assert handler.passes_type_filters(listing, search) is False


def test_passes_type_filters_accepts_matching_size():
    handler = ApparelHandler()
    search = _make_search_config(sizes=[10, 10.5, 11])
    listing = Listing(source="t", listing_id="1", title="t", price_usd=250, url="u", size=10.5)
    assert handler.passes_type_filters(listing, search) is True


def test_passes_type_filters_skips_size_check_when_unconfigured():
    handler = ApparelHandler()
    search = _make_search_config(sizes=[])
    listing = Listing(source="t", listing_id="1", title="t", price_usd=250, url="u", size=6.0)
    assert handler.passes_type_filters(listing, search) is True


def test_passes_type_filters_rejects_wrong_color():
    handler = ApparelHandler()
    search = _make_search_config(colors=["black", "brown"])
    listing = Listing(source="t", listing_id="1", title="t", price_usd=250, url="u", color="oxblood")
    assert handler.passes_type_filters(listing, search) is False


# ── score_bonuses() ─────────────────────────────────────────────────

def test_score_bonuses_rewards_preferred_brand():
    handler = ApparelHandler()
    search = _make_search_config(preferred_brands=["Red Wing"])
    preferred = Listing(source="t", listing_id="1", title="t", price_usd=250, url="u", brand="Red Wing")
    other = Listing(source="t", listing_id="2", title="t", price_usd=250, url="u", brand="Generic")
    assert handler.score_bonuses(preferred, search) > handler.score_bonuses(other, search)


def test_score_bonuses_rewards_deadstock_condition():
    handler = ApparelHandler()
    search = _make_search_config()
    new_in_box = Listing(source="t", listing_id="1", title="Red Wing NIB Size 10.5",
                          price_usd=250, url="u", condition="New in Box")
    used = Listing(source="t", listing_id="2", title="Red Wing Size 10.5",
                    price_usd=250, url="u", condition="Used")
    assert handler.score_bonuses(new_in_box, search) > handler.score_bonuses(used, search)


def test_score_bonuses_rewards_exact_size_match():
    handler = ApparelHandler()
    search = _make_search_config(sizes=[10.5])
    match = Listing(source="t", listing_id="1", title="t", price_usd=250, url="u", size=10.5)
    no_match = Listing(source="t", listing_id="2", title="t", price_usd=250, url="u", size=9.0)
    assert handler.score_bonuses(match, search) > handler.score_bonuses(no_match, search)


# ── min_price_usd() ─────────────────────────────────────────────────

def test_min_price_usd_is_apparel_floor():
    handler = ApparelHandler()
    assert handler.min_price_usd(_make_search_config()) == MINIMUM_PRICE_USD


# ── BaseScraper dispatch (proves scrapers need zero apparel-specific code) ──

def test_parse_common_specs_dispatches_to_apparel_handler():
    search = _make_search_config()
    scraper = FakeScraper(_make_fake_config(search))
    specs = scraper.parse_common_specs("Red Wing Iron Ranger Size 10.5 Black Boots")
    assert specs["size"] == 10.5
    assert specs["brand"] == "Red Wing"
    assert specs["color"] == "black"


def test_passes_filters_rejects_accessory_via_apparel_handler():
    search = _make_search_config()
    scraper = FakeScraper(_make_fake_config(search))
    listing = _make_listing(title="Red Wing Boot Laces Only")
    assert scraper.passes_filters(listing) is False


def test_passes_filters_rejects_below_apparel_min_price():
    search = _make_search_config()
    scraper = FakeScraper(_make_fake_config(search))
    listing = _make_listing(price_usd=20.0)
    assert scraper.passes_filters(listing) is False


def test_passes_filters_accepts_real_boot_listing():
    search = _make_search_config(sizes=[10.5])
    scraper = FakeScraper(_make_fake_config(search))
    listing = _make_listing()
    assert scraper.passes_filters(listing) is True


# ── get_enabled_scrapers() integration: general marketplaces opt in,
#    Apple-only storefronts automatically sit out ────────────────────

def _make_full_config(product_type: str) -> Config:
    """A minimal-but-real Config wired for get_enabled_scrapers()."""
    general = SiteConfig(enabled=True)  # applicable_product_types=None (default)
    apple_only = SiteConfig(enabled=True, applicable_product_types=["electronics"])
    sites = SitesConfig(
        ebay=general, swappa=general, backmarket=general, mercari=general,
        offerup=general, craigslist=general, facebook=general,
        apple_refurb=apple_only, bestbuy=apple_only, newegg=apple_only, gazelle=apple_only,
    )
    search = _make_search_config(product_type=product_type)
    return Config(
        searches=[search], price=SimpleNamespace(absolute_max_usd=1000),
        sites=sites, alerts=None, database=None, schedule={}, price_drop=None,
        search=search,
    )


def test_get_enabled_scrapers_includes_general_marketplaces_for_apparel():
    import main
    config = _make_full_config("apparel")
    scrapers = main.get_enabled_scrapers(config)
    names = {s.source_name for s in scrapers}
    assert "ebay" in names
    assert "swappa" in names
    assert "backmarket" in names


def test_get_enabled_scrapers_excludes_apple_only_sites_for_apparel():
    import main
    config = _make_full_config("apparel")
    scrapers = main.get_enabled_scrapers(config)
    names = {s.source_name for s in scrapers}
    assert "apple_refurb" not in names
    assert "bestbuy" not in names
    assert "newegg" not in names
    assert "gazelle" not in names


def test_get_enabled_scrapers_still_includes_everything_for_electronics():
    import main
    config = _make_full_config("electronics")
    scrapers = main.get_enabled_scrapers(config)
    names = {s.source_name for s in scrapers}
    assert "apple_refurb" in names
    assert "ebay" in names
