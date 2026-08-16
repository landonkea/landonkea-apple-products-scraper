# ───────────────────────────────────────────────────────────────────
# Tests for the ebike product type (src/product_types/ebike.py)
# ───────────────────────────────────────────────────────────────────
# Mirrors test_product_types_apparel.py's structure (unit tests on the
# handler directly, dispatch tests through BaseScraper, a
# get_enabled_scrapers() integration check), plus ebike-specific
# coverage this category needs that apparel didn't: nominal-vs-peak
# motor wattage parsing, the weight-capacity hard filter, and battery
# Wh computation.
#
# HOW TO RUN:
#   pytest tests/test_product_types_ebike.py -v
# ───────────────────────────────────────────────────────────────────

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import Config, SearchConfig, SiteConfig, SitesConfig
from database import Listing
from product_types import PRODUCT_TYPES
from product_types.ebike import (
    EbikeHandler,
    MINIMUM_PRICE_USD,
    MIN_ACCEPTABLE_WEIGHT_CAPACITY_LB,
    extract_brand,
    extract_wheel_size_in,
    extract_fat_tire,
    extract_step_through,
    extract_folding,
    extract_battery_voltage_ah,
    extract_motor_watts,
    extract_brake_type,
    extract_suspension,
    extract_ul_certified,
    extract_weight_capacity_lb,
)
from scrapers.base import BaseScraper, ScrapedListing


def _make_search_config(**overrides) -> SearchConfig:
    defaults = dict(
        product_name="folding step through electric bike",
        chip=None,
        chip_fallback=None,
        screen_sizes=[],
        ram_gb_primary=None,
        ram_gb_fallback=None,
        storage_gb_min=None,
        storage_gb_max=None,
        results_per_size=40,
        location=None,
        product_type="ebike",
        preferred_brands=["Lectric", "Aventon", "Himiway"],
    )
    defaults.update(overrides)
    return SearchConfig(**defaults)


class FakeScraper(BaseScraper):
    """Minimal concrete BaseScraper subclass, scrape() is abstract and unused here."""

    def scrape(self):
        return []


def _make_fake_config(search: SearchConfig):
    return SimpleNamespace(search=search, price=SimpleNamespace(absolute_max_usd=2000))


def _make_listing(**overrides) -> ScrapedListing:
    defaults = dict(
        source="test", listing_id="1",
        title="Lectric XPedition 48V 20Ah Folding Step Thru Fat Tire Electric Bike",
        price_usd=1200.0, url="http://example.com", condition="Used",
        ram_gb=None, storage_gb=None, screen_size=None, chip=None, location=None,
        brand="Lectric", wheel_size_in=20.0, fat_tire=True, step_through=True,
        folding=True, battery_voltage=48, battery_ah=20.0, battery_wh=960.0,
        motor_watts_nominal=750, motor_watts_peak=1200, weight_capacity_lb=400,
        brake_type="hydraulic", suspension=True, ul_certified=True,
    )
    defaults.update(overrides)
    return ScrapedListing(**defaults)


# ── Registry ─────────────────────────────────────────────────────────

def test_registry_has_ebike_handler():
    assert "ebike" in PRODUCT_TYPES
    assert isinstance(PRODUCT_TYPES["ebike"], EbikeHandler)


# ── Spec parsing ────────────────────────────────────────────────────

def test_extract_brand_finds_known_brand():
    assert extract_brand("Aventon Level.2 Commuter E-Bike") == "Aventon"


def test_extract_brand_returns_none_for_unknown_brand():
    assert extract_brand("Generic Ebike Brand XYZ") is None


def test_extract_wheel_size_in_finds_target_size():
    assert extract_wheel_size_in('20" Folding Fat Tire Ebike') == 20.0
    assert extract_wheel_size_in("16 inch folding ebike") == 16.0


def test_extract_wheel_size_in_ignores_non_target_size():
    # 26" isn't one of the rider's target sizes (16/20/24).
    assert extract_wheel_size_in('26" mountain ebike') is None


def test_extract_fat_tire_finds_keyword():
    assert extract_fat_tire("Fat Tire Folding Ebike") is True


def test_extract_fat_tire_finds_dimension_notation():
    assert extract_fat_tire("20x4 folding ebike") is True


def test_extract_fat_tire_false_for_normal_tire():
    assert extract_fat_tire("700c folding ebike") is False


def test_extract_step_through_finds_keyword_variants():
    assert extract_step_through("Step Thru Folding Ebike") is True
    assert extract_step_through("Step-Through Commuter Ebike") is True
    assert extract_step_through("StepThru Ebike") is True


def test_extract_step_through_false_when_absent():
    assert extract_step_through("Standard Diamond Frame Ebike") is False


def test_extract_folding_finds_keyword():
    assert extract_folding("Folding Step Thru Ebike") is True
    assert extract_folding("Fold Up Commuter Ebike") is True


def test_extract_battery_voltage_ah_finds_both():
    voltage, ah = extract_battery_voltage_ah("48V 20Ah Removable Battery Ebike")
    assert voltage == 48
    assert ah == 20.0


def test_extract_battery_voltage_ah_handles_decimal_ah():
    voltage, ah = extract_battery_voltage_ah("36V 10.4Ah Ebike")
    assert voltage == 36
    assert ah == 10.4


def test_extract_motor_watts_unqualified_is_nominal_not_peak():
    # A bare "1200W" with no qualifier must NOT be recorded as peak --
    # this is the rider brief's explicit "don't call it a 1200W
    # nominal motor" concern, inverted: don't call an unqualified
    # figure peak either, since it's genuinely ambiguous and the
    # common case is a single stated wattage meant as nominal.
    nominal, peak = extract_motor_watts("1200W Folding Ebike")
    assert nominal == 1200
    assert peak is None


def test_extract_motor_watts_distinguishes_nominal_and_peak():
    nominal, peak = extract_motor_watts("750W Nominal / 1200W Peak Motor Ebike")
    assert nominal == 750
    assert peak == 1200


def test_extract_motor_watts_peak_keyword_not_misread_as_nominal():
    nominal, peak = extract_motor_watts("1200W Peak Motor Folding Ebike")
    assert peak == 1200
    assert nominal is None


def test_extract_brake_type_hydraulic():
    assert extract_brake_type("Hydraulic Disc Brake Ebike") == "hydraulic"


def test_extract_brake_type_mechanical_disc():
    assert extract_brake_type("Mechanical Disc Brake Ebike") == "mechanical"


def test_extract_brake_type_rim():
    assert extract_brake_type("Rim Brake Folding Ebike") == "rim"


def test_extract_suspension_finds_keyword():
    assert extract_suspension("Front Suspension Fork Folding Ebike") is True


def test_extract_ul_certified_finds_2849_and_2271():
    assert extract_ul_certified("UL 2849 Certified Ebike") is True
    assert extract_ul_certified("UL2271 Battery Ebike") is True


def test_extract_ul_certified_false_when_absent():
    assert extract_ul_certified("Folding Ebike") is False


def test_extract_weight_capacity_lb_finds_capacity_phrasing():
    assert extract_weight_capacity_lb("400lb Capacity Folding Ebike") == 400
    assert extract_weight_capacity_lb("350 lbs weight limit ebike") == 350


def test_extract_weight_capacity_lb_ignores_bare_weight_mention():
    # A bare "65lb" bike-weight mention (not a capacity/limit) should
    # not be misread as a rider weight capacity.
    assert extract_weight_capacity_lb("65lb Folding Ebike, Great Condition") is None


def test_parse_specs_includes_electronics_shaped_keys_as_none():
    # Critical: general scrapers' existing electronics-field bracket
    # access (specs["ram_gb"], etc.) must not KeyError for an ebike
    # search, see ebike.py's parse_specs() docstring.
    handler = EbikeHandler()
    specs = handler.parse_specs("Lectric XPedition Folding Ebike")
    for key in ("ram_gb", "storage_gb", "screen_size", "chip", "cpu_cores", "gpu_cores"):
        assert key in specs
        assert specs[key] is None


def test_parse_specs_computes_battery_wh():
    handler = EbikeHandler()
    specs = handler.parse_specs("48V 20Ah Folding Ebike")
    assert specs["battery_wh"] == 960.0


def test_parse_specs_battery_wh_none_when_incomplete():
    handler = EbikeHandler()
    specs = handler.parse_specs("48V Folding Ebike")  # no Ah stated
    assert specs["battery_wh"] is None


# ── is_relevant() ───────────────────────────────────────────────────

def test_is_relevant_rejects_battery_only_listing():
    handler = EbikeHandler()
    search = _make_search_config()
    assert handler.is_relevant("Ebike Battery Only 48V 20Ah", search) is False


def test_is_relevant_rejects_frame_only():
    handler = EbikeHandler()
    search = _make_search_config()
    assert handler.is_relevant("Folding Ebike Frame Only", search) is False


def test_is_relevant_rejects_dead_battery_condition():
    handler = EbikeHandler()
    search = _make_search_config()
    assert handler.is_relevant("Folding Ebike", search, condition="Dead battery, does not hold charge") is False


def test_is_relevant_accepts_real_listing():
    handler = EbikeHandler()
    search = _make_search_config()
    assert handler.is_relevant("Lectric XPedition Folding Step Thru Ebike", search) is True


# ── passes_type_filters() (the one hard filter) ─────────────────────

def test_passes_type_filters_rejects_low_weight_capacity():
    handler = EbikeHandler()
    search = _make_search_config()
    listing = Listing(source="t", listing_id="1", title="t", price_usd=800, url="u",
                       weight_capacity_lb=250)
    assert handler.passes_type_filters(listing, search) is False


def test_passes_type_filters_accepts_at_minimum_threshold():
    handler = EbikeHandler()
    search = _make_search_config()
    listing = Listing(source="t", listing_id="1", title="t", price_usd=800, url="u",
                       weight_capacity_lb=MIN_ACCEPTABLE_WEIGHT_CAPACITY_LB)
    assert handler.passes_type_filters(listing, search) is True


def test_passes_type_filters_accepts_unstated_capacity():
    # No capacity stated at all -- can't verify from title, so not
    # rejected, see module docstring's HARD FILTERS design note.
    handler = EbikeHandler()
    search = _make_search_config()
    listing = Listing(source="t", listing_id="1", title="t", price_usd=800, url="u",
                       weight_capacity_lb=None)
    assert handler.passes_type_filters(listing, search) is True


# ── score_bonuses() ─────────────────────────────────────────────────

def test_score_bonuses_rewards_higher_weight_capacity():
    handler = EbikeHandler()
    search = _make_search_config()
    cap_400 = Listing(source="t", listing_id="1", title="t", price_usd=800, url="u", weight_capacity_lb=400)
    cap_330 = Listing(source="t", listing_id="2", title="t", price_usd=800, url="u", weight_capacity_lb=330)
    assert handler.score_bonuses(cap_400, search) > handler.score_bonuses(cap_330, search)


def test_score_bonuses_rewards_step_through():
    handler = EbikeHandler()
    search = _make_search_config()
    step_thru = Listing(source="t", listing_id="1", title="t", price_usd=800, url="u", step_through=True)
    diamond = Listing(source="t", listing_id="2", title="t", price_usd=800, url="u", step_through=False)
    assert handler.score_bonuses(step_thru, search) > handler.score_bonuses(diamond, search)


def test_score_bonuses_rewards_higher_battery_ah_tier():
    handler = EbikeHandler()
    search = _make_search_config()
    ah_20 = Listing(source="t", listing_id="1", title="t", price_usd=800, url="u", battery_ah=20.0)
    ah_10 = Listing(source="t", listing_id="2", title="t", price_usd=800, url="u", battery_ah=10.0)
    assert handler.score_bonuses(ah_20, search) > handler.score_bonuses(ah_10, search)


def test_score_bonuses_penalizes_rim_brakes():
    handler = EbikeHandler()
    search = _make_search_config()
    hydraulic = Listing(source="t", listing_id="1", title="t", price_usd=800, url="u", brake_type="hydraulic")
    rim = Listing(source="t", listing_id="2", title="t", price_usd=800, url="u", brake_type="rim")
    assert handler.score_bonuses(hydraulic, search) > handler.score_bonuses(rim, search)


def test_score_bonuses_rewards_preferred_brand():
    handler = EbikeHandler()
    search = _make_search_config(preferred_brands=["Lectric"])
    preferred = Listing(source="t", listing_id="1", title="t", price_usd=800, url="u", brand="Lectric")
    other = Listing(source="t", listing_id="2", title="t", price_usd=800, url="u", brand="Generic")
    assert handler.score_bonuses(preferred, search) > handler.score_bonuses(other, search)


def test_score_bonuses_rewards_ul_certification():
    handler = EbikeHandler()
    search = _make_search_config()
    certified = Listing(source="t", listing_id="1", title="t", price_usd=800, url="u", ul_certified=True)
    uncertified = Listing(source="t", listing_id="2", title="t", price_usd=800, url="u", ul_certified=False)
    assert handler.score_bonuses(certified, search) > handler.score_bonuses(uncertified, search)


# ── min_price_usd() ─────────────────────────────────────────────────

def test_min_price_usd_is_ebike_floor():
    handler = EbikeHandler()
    assert handler.min_price_usd(_make_search_config()) == MINIMUM_PRICE_USD


# ── BaseScraper dispatch (proves scrapers need zero ebike-specific code) ──

def test_parse_common_specs_dispatches_to_ebike_handler():
    search = _make_search_config()
    scraper = FakeScraper(_make_fake_config(search))
    specs = scraper.parse_common_specs("Lectric XPedition 48V 20Ah Folding Step Thru Ebike")
    assert specs["brand"] == "Lectric"
    assert specs["battery_voltage"] == 48
    assert specs["battery_ah"] == 20.0
    assert specs["step_through"] is True
    assert specs["folding"] is True


def test_passes_filters_rejects_accessory_via_ebike_handler():
    search = _make_search_config()
    scraper = FakeScraper(_make_fake_config(search))
    listing = _make_listing(title="Ebike Battery Only 48V 20Ah")
    assert scraper.passes_filters(listing) is False


def test_passes_filters_rejects_below_ebike_min_price():
    search = _make_search_config()
    scraper = FakeScraper(_make_fake_config(search))
    listing = _make_listing(price_usd=50.0)
    assert scraper.passes_filters(listing) is False


def test_passes_filters_accepts_real_ebike_listing():
    search = _make_search_config()
    scraper = FakeScraper(_make_fake_config(search))
    listing = _make_listing()
    assert scraper.passes_filters(listing) is True


# ── get_enabled_scrapers() integration: general marketplaces +
#    pinkbike opt in, Apple-only storefronts (now including swappa)
#    automatically sit out ───────────────────────────────────────────

def _make_full_config(product_type: str) -> Config:
    """A minimal-but-real Config wired for get_enabled_scrapers()."""
    general = SiteConfig(enabled=True)  # applicable_product_types=None (default)
    apple_only = SiteConfig(enabled=True, applicable_product_types=["electronics"])
    ebike_only = SiteConfig(enabled=True, applicable_product_types=["ebike"])
    sites = SitesConfig(
        ebay=general, swappa=apple_only, backmarket=general, mercari=general,
        offerup=general, craigslist=general, facebook=general,
        apple_refurb=apple_only, bestbuy=apple_only, newegg=apple_only, gazelle=apple_only,
        pinkbike=ebike_only,
    )
    search = _make_search_config(product_type=product_type)
    return Config(
        searches=[search], price=SimpleNamespace(absolute_max_usd=2000),
        sites=sites, alerts=None, database=None, schedule={}, price_drop=None,
        search=search,
    )


def test_get_enabled_scrapers_includes_general_marketplaces_and_pinkbike_for_ebike():
    import main
    config = _make_full_config("ebike")
    scrapers = main.get_enabled_scrapers(config)
    names = {s.source_name for s in scrapers}
    assert "ebay" in names
    assert "craigslist" in names
    assert "pinkbike" in names


def test_get_enabled_scrapers_excludes_apple_only_sites_for_ebike():
    import main
    config = _make_full_config("ebike")
    scrapers = main.get_enabled_scrapers(config)
    names = {s.source_name for s in scrapers}
    assert "apple_refurb" not in names
    assert "bestbuy" not in names
    assert "newegg" not in names
    assert "gazelle" not in names
    assert "swappa" not in names


def test_get_enabled_scrapers_excludes_pinkbike_for_electronics():
    import main
    config = _make_full_config("electronics")
    scrapers = main.get_enabled_scrapers(config)
    names = {s.source_name for s in scrapers}
    assert "pinkbike" not in names
    assert "swappa" in names
