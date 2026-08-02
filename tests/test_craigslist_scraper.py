# ───────────────────────────────────────────────────────────────────
# Tests for the Craigslist scraper's HTML-parsing helpers
# (src/scrapers/craigslist.py)
# ───────────────────────────────────────────────────────────────────
# These are network-free unit tests: they build small BeautifulSoup
# fragments mimicking Craigslist's real listing-card HTML (per the
# module docstring's "LIVE-TESTING FINDINGS", confirmed via live
# `curl` fetches against www.craigslist.org) and check what each
# parsing helper extracts from them. The network-calling scrape()
# method itself is intentionally NOT tested here — it needs live HTTP
# access, which isn't how this project's test suite works (see
# test_scrapers.py).
#
# HOW TO RUN:
#   pytest tests/test_craigslist_scraper.py -v
# ───────────────────────────────────────────────────────────────────

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bs4 import BeautifulSoup

from scrapers.craigslist import CraigslistScraper


def make_scraper(product_name="MacBook Pro", regions=None, absolute_max_usd=8000, results_per_size=30):
    """
    Build a CraigslistScraper wired to a minimal fake config.

    WHY A FAKE CONFIG: The parsing/URL-building helpers under test
    here only ever read config.search.product_name, config.price.
    absolute_max_usd, and config.sites.craigslist.regions — a
    SimpleNamespace covering just those fields avoids building out a
    full Config dataclass tree for no benefit (same pattern as
    test_newegg_scraper.py / test_gazelle_scraper.py).
    """
    fake_search = SimpleNamespace(
        product_name=product_name, results_per_size=results_per_size, product_type="electronics"
    )
    fake_price = SimpleNamespace(absolute_max_usd=absolute_max_usd)
    fake_sites = SimpleNamespace(craigslist=SimpleNamespace(regions=regions))
    fake_config = SimpleNamespace(search=fake_search, price=fake_price, sites=fake_sites)
    return CraigslistScraper(fake_config)


def card_from_html(html: str):
    """Parse an HTML fragment and return its outer element (mimics one <li>)."""
    return BeautifulSoup(html, "lxml")


# ── regions ──────────────────────────────────────────────────────

def test_regions_defaults_to_phoenix_when_unset():
    """config.sites.craigslist.regions=None falls back to DEFAULT_REGIONS."""
    scraper = make_scraper(regions=None)
    assert scraper.regions == ["phoenix"]


def test_regions_defaults_to_phoenix_when_empty_list():
    """An empty list also falls back to DEFAULT_REGIONS (falsy, same as None)."""
    scraper = make_scraper(regions=[])
    assert scraper.regions == ["phoenix"]


def test_regions_uses_configured_list():
    """A configured multi-region list (multiple states) wins."""
    scraper = make_scraper(regions=["phoenix", "tucson", "losangeles"])
    assert scraper.regions == ["phoenix", "tucson", "losangeles"]


# ── search URL ───────────────────────────────────────────────────

def test_build_search_url_uses_region_category_and_max_price():
    scraper = make_scraper("MacBook Pro", regions=["phoenix"], absolute_max_usd=8000)
    url = scraper._build_search_url("phoenix")
    assert url == (
        "https://www.craigslist.org/search/area/phoenix"
        "?cat=sss&query=MacBook%20Pro&max_price=8000"
    )


def test_build_search_url_reflects_given_region():
    scraper = make_scraper("MacBook Pro", regions=["tucson"], absolute_max_usd=500)
    url = scraper._build_search_url("tucson")
    assert url.startswith("https://www.craigslist.org/search/area/tucson")
    assert "max_price=500" in url


def test_build_search_url_takes_region_as_argument_not_config():
    """_build_search_url() builds a URL for whatever region is passed in,
    independent of what's configured — scrape() calls it once per region."""
    scraper = make_scraper("MacBook Pro", regions=["phoenix"], absolute_max_usd=1000)
    url = scraper._build_search_url("sfbay")
    assert url.startswith("https://www.craigslist.org/search/area/sfbay")


# ── price parsing ────────────────────────────────────────────────

def test_parse_price_strips_dollar_and_comma():
    scraper = make_scraper()
    assert scraper._parse_price("$1,700") == 1700.0


def test_parse_price_no_comma():
    scraper = make_scraper()
    assert scraper._parse_price("$300") == 300.0


def test_parse_price_returns_none_for_no_digits():
    scraper = make_scraper()
    assert scraper._parse_price("Free") is None


# ── listing ID ───────────────────────────────────────────────────

def test_get_listing_id_uses_last_url_segment():
    scraper = make_scraper()
    url = "https://www.craigslist.org/view/d/apple-macbook-pro/c9yAuUSPCiAE7juezJsoux"
    assert scraper._get_listing_id(url) == "craigslist-c9yAuUSPCiAE7juezJsoux"


def test_get_listing_id_falls_back_for_empty_url():
    scraper = make_scraper()
    listing_id = scraper._get_listing_id("")
    assert listing_id.startswith("craigslist-url_")


# ── single-item parsing ──────────────────────────────────────────

REAL_LISTING_HTML = """
<li class="cl-static-search-result" title="Macbook Pro 14 Inch - M5 Pro - 24 GB Ram 1TB SSD">
  <a href="https://www.craigslist.org/view/d/phoenix-macbook-pro-14-inch-m5-pro-24/c9yAuUSPCiAE7juezJsoux">
    <div class="title">Macbook Pro 14 Inch - M5 Pro - 24 GB Ram 1TB SSD</div>
    <div class="details">
      <div class="price">$1,700</div>
      <div class="location">Phoenix</div>
    </div>
  </a>
</li>
"""


def test_parse_single_item_extracts_all_fields():
    """Mirrors a real listing card confirmed live (see module docstring)."""
    scraper = make_scraper()
    item = card_from_html(REAL_LISTING_HTML).select_one("li.cl-static-search-result")
    listing = scraper._parse_single_item(item)

    assert listing is not None
    assert listing.source == "craigslist"
    assert listing.title == "Macbook Pro 14 Inch - M5 Pro - 24 GB Ram 1TB SSD"
    assert listing.price_usd == 1700.0
    assert listing.url == (
        "https://www.craigslist.org/view/d/phoenix-macbook-pro-14-inch-m5-pro-24/"
        "c9yAuUSPCiAE7juezJsoux"
    )
    assert listing.listing_id == "craigslist-c9yAuUSPCiAE7juezJsoux"
    assert listing.location == "Phoenix"
    # Craigslist has no structured condition field — always None,
    # honestly, per the module docstring.
    assert listing.condition is None
    # Specs get parsed out of the title via parse_common_specs().
    assert listing.ram_gb == 24
    assert listing.storage_gb == 1024


def test_parse_single_item_returns_none_for_missing_title():
    scraper = make_scraper()
    html = (
        '<li class="cl-static-search-result">'
        '<a href="https://www.craigslist.org/view/d/x/1">'
        '<div class="details"><div class="price">$100</div></div>'
        "</a></li>"
    )
    item = card_from_html(html).select_one("li.cl-static-search-result")
    assert scraper._parse_single_item(item) is None


def test_parse_single_item_returns_none_for_missing_price():
    scraper = make_scraper()
    html = (
        '<li class="cl-static-search-result">'
        '<a href="https://www.craigslist.org/view/d/x/1">'
        '<div class="title">Something</div>'
        "</a></li>"
    )
    item = card_from_html(html).select_one("li.cl-static-search-result")
    assert scraper._parse_single_item(item) is None


def test_parse_single_item_returns_none_for_missing_url():
    scraper = make_scraper()
    html = (
        '<li class="cl-static-search-result">'
        '<div class="title">Something</div>'
        '<div class="details"><div class="price">$100</div></div>'
        "</li>"
    )
    item = card_from_html(html).select_one("li.cl-static-search-result")
    assert scraper._parse_single_item(item) is None


def test_parse_single_item_location_none_when_missing():
    scraper = make_scraper()
    html = (
        '<li class="cl-static-search-result">'
        '<a href="https://www.craigslist.org/view/d/x/1">'
        '<div class="title">MacBook Pro 128GB</div>'
        '<div class="details"><div class="price">$500</div></div>'
        "</a></li>"
    )
    item = card_from_html(html).select_one("li.cl-static-search-result")
    listing = scraper._parse_single_item(item)
    assert listing is not None
    assert listing.location is None


# ── scrape() — multi-region looping ─────────────────────────────────
# scrape() itself needs live HTTP for _fetch_cards()'s fetch_page()
# call, so these tests mock _fetch_cards() directly (network-free,
# same spirit as the rest of this file) to verify the multi-region
# aggregation/dedup/cap logic without hitting the network.

def _card(listing_id_suffix: str, title: str = "MacBook Pro 128GB", price: str = "$500"):
    html = (
        '<li class="cl-static-search-result">'
        f'<a href="https://www.craigslist.org/view/d/x/{listing_id_suffix}">'
        f'<div class="title">{title}</div>'
        f'<div class="details"><div class="price">{price}</div>'
        '<div class="location">Somewhere</div></div>'
        "</a></li>"
    )
    return card_from_html(html).select_one("li.cl-static-search-result")


def test_scrape_aggregates_across_all_configured_regions(monkeypatch):
    scraper = make_scraper(regions=["phoenix", "tucson"], results_per_size=30)
    cards_by_region = {
        "phoenix": [_card("p1"), _card("p2")],
        "tucson": [_card("t1")],
    }
    monkeypatch.setattr(scraper, "_fetch_cards", lambda region: cards_by_region[region])
    # passes_filters() delegates to the electronics ProductTypeHandler,
    # which needs a full SearchConfig (chip_options, model_keywords,
    # etc.) that the minimal fake_search in make_scraper() doesn't
    # build — not what these tests are checking (that's covered
    # elsewhere), so it's stubbed to always-pass here.
    monkeypatch.setattr(scraper, "passes_filters", lambda listing: True)

    results = scraper.scrape()

    assert len(results) == 3
    assert {r.listing_id for r in results} == {
        "craigslist-p1", "craigslist-p2", "craigslist-t1",
    }


def test_scrape_stops_once_results_per_size_reached(monkeypatch):
    scraper = make_scraper(regions=["phoenix", "tucson"], results_per_size=1)
    cards_by_region = {
        "phoenix": [_card("p1"), _card("p2")],
        "tucson": [_card("t1")],
    }
    monkeypatch.setattr(scraper, "_fetch_cards", lambda region: cards_by_region[region])
    # passes_filters() delegates to the electronics ProductTypeHandler,
    # which needs a full SearchConfig (chip_options, model_keywords,
    # etc.) that the minimal fake_search in make_scraper() doesn't
    # build — not what these tests are checking (that's covered
    # elsewhere), so it's stubbed to always-pass here.
    monkeypatch.setattr(scraper, "passes_filters", lambda listing: True)

    results = scraper.scrape()

    # Caps at results_per_size and never even fetches tucson.
    assert len(results) == 1


def test_scrape_dedupes_listing_id_across_regions(monkeypatch):
    scraper = make_scraper(regions=["phoenix", "tucson"], results_per_size=30)
    # Same listing_id ("dupe") appears under both regions — only
    # counted once.
    cards_by_region = {
        "phoenix": [_card("dupe")],
        "tucson": [_card("dupe")],
    }
    monkeypatch.setattr(scraper, "_fetch_cards", lambda region: cards_by_region[region])
    # passes_filters() delegates to the electronics ProductTypeHandler,
    # which needs a full SearchConfig (chip_options, model_keywords,
    # etc.) that the minimal fake_search in make_scraper() doesn't
    # build — not what these tests are checking (that's covered
    # elsewhere), so it's stubbed to always-pass here.
    monkeypatch.setattr(scraper, "passes_filters", lambda listing: True)

    results = scraper.scrape()

    assert len(results) == 1


def test_scrape_continues_past_a_region_with_no_cards(monkeypatch):
    """A region that fails to fetch (empty list, per _fetch_cards's own
    error handling) shouldn't stop other regions from being scraped."""
    scraper = make_scraper(regions=["phoenix", "tucson"], results_per_size=30)
    cards_by_region = {
        "phoenix": [],
        "tucson": [_card("t1")],
    }
    monkeypatch.setattr(scraper, "_fetch_cards", lambda region: cards_by_region[region])
    # passes_filters() delegates to the electronics ProductTypeHandler,
    # which needs a full SearchConfig (chip_options, model_keywords,
    # etc.) that the minimal fake_search in make_scraper() doesn't
    # build — not what these tests are checking (that's covered
    # elsewhere), so it's stubbed to always-pass here.
    monkeypatch.setattr(scraper, "passes_filters", lambda listing: True)

    results = scraper.scrape()

    assert len(results) == 1
    assert results[0].listing_id == "craigslist-t1"
