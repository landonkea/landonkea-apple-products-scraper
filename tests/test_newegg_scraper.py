# ───────────────────────────────────────────────────────────────────
# Tests for the Newegg scraper's HTML-parsing helpers
# (src/scrapers/newegg.py)
# ───────────────────────────────────────────────────────────────────
# These are network-free unit tests: they build small BeautifulSoup
# fragments mimicking Newegg's real listing-card HTML (per the module
# docstring's "LISTING CARD STRUCTURE" notes, confirmed via live
# fetches) and check what each parsing helper extracts from them. The
# network-calling scrape() method itself is intentionally NOT tested
# here — it needs live HTTP access, which isn't how this project's
# test suite works (see test_scrapers.py).
#
# HOW TO RUN:
#   pytest tests/test_newegg_scraper.py -v
# ───────────────────────────────────────────────────────────────────

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bs4 import BeautifulSoup

from scrapers.newegg import NeweggScraper


def make_scraper(product_name="MacBook Pro"):
    """
    Build a NeweggScraper wired to a minimal fake config.

    WHY A FAKE CONFIG: The parsing helpers under test here never read
    self.config except for product_name (used to build the search
    URL) — a SimpleNamespace with just that field avoids building out
    a full Config dataclass tree for no benefit.
    """
    fake_search = SimpleNamespace(product_name=product_name, results_per_size=30, product_type="electronics")
    fake_config = SimpleNamespace(search=fake_search)
    return NeweggScraper(fake_config)


def card_from_html(html: str):
    """Parse an HTML fragment and return its outer element (mimics a `.item-cell`)."""
    return BeautifulSoup(html, "lxml")


def test_build_search_url_bare_query_no_sort():
    """Query is the bare product name, no sort param — see module docstring."""
    scraper = make_scraper("MacBook Pro")
    assert scraper._build_search_url(1) == "https://www.newegg.com/p/pl?d=MacBook+Pro"


def test_build_search_url_adds_page_param_after_page_1():
    scraper = make_scraper("MacBook Pro")
    assert scraper._build_search_url(2) == "https://www.newegg.com/p/pl?d=MacBook+Pro&page=2"


def test_get_price_dollars_and_cents():
    """Price split across <strong> (dollars) and <sup> (cents) combines correctly."""
    scraper = make_scraper()
    item = card_from_html(
        '<div class="item-cell"><ul class="price">'
        '<li class="price-current">$<strong>519</strong><sup>.99</sup></li>'
        "</ul></div>"
    )
    assert scraper._get_price(item) == 519.99


def test_get_price_whole_dollars_no_cents():
    """Falls back to a whole-dollar price when no cents are shown."""
    scraper = make_scraper()
    item = card_from_html(
        '<div class="item-cell"><ul class="price">'
        '<li class="price-current">$<strong>1200</strong></li>'
        "</ul></div>"
    )
    assert scraper._get_price(item) == 1200.0


def test_get_price_missing_returns_none():
    scraper = make_scraper()
    item = card_from_html('<div class="item-cell"></div>')
    assert scraper._get_price(item) is None


def test_get_condition_present():
    scraper = make_scraper()
    item = card_from_html(
        '<div class="item-cell"><span class="item-open-box-italic">Refurbished</span></div>'
    )
    assert scraper._get_condition(item) == "Refurbished"


def test_get_condition_missing_returns_none():
    scraper = make_scraper()
    item = card_from_html('<div class="item-cell"></div>')
    assert scraper._get_condition(item) is None


def test_get_listing_id_from_container_id():
    """Newegg tags the outer container with its internal item number as `id`."""
    scraper = make_scraper()
    item = card_from_html(
        '<div class="item-cell"><div class="item-container" id="9SIA7WPKAR3575"></div></div>'
    )
    url = "https://www.newegg.com/p/9SIA7WPKAR3575"
    assert scraper._get_listing_id(item, url) == "9SIA7WPKAR3575"


def test_get_listing_id_falls_back_to_url_sku():
    """No container id -> fall back to the `/p/<sku>` path segment."""
    scraper = make_scraper()
    item = card_from_html('<div class="item-cell"></div>')
    url = "https://www.newegg.com/apple-macbook-pro/p/N82E16834260006"
    assert scraper._get_listing_id(item, url) == "N82E16834260006"


def test_get_listing_id_falls_back_to_hash():
    """No container id and no /p/ segment -> hash of the URL as a last resort."""
    scraper = make_scraper()
    item = card_from_html('<div class="item-cell"></div>')
    url = "https://www.newegg.com/some/other/path"
    assert scraper._get_listing_id(item, url) == f"url_{hash(url)}"


def test_parse_single_item_full_card():
    """A realistic listing card parses into the expected raw fields."""
    scraper = make_scraper()
    html = """
    <div class="item-cell">
      <div class="item-container" id="9SIA7WPKAR3575">
        <a class="item-title" href="/Apple-MacBook-Pro/p/N82E16834260006">
          <span class="item-open-box-italic">Refurbished</span>
          Apple MacBook Pro 14" M3 Max 128GB Memory 2TB SSD
        </a>
        <ul class="price">
          <li class="price-current">$<strong>5199</strong><sup>.99</sup></li>
        </ul>
      </div>
    </div>
    """
    item = card_from_html(html).select_one(".item-cell")
    listing = scraper._parse_single_item(item)
    assert listing is not None
    assert listing.source == "newegg"
    assert listing.listing_id == "9SIA7WPKAR3575"
    assert listing.price_usd == 5199.99
    assert listing.condition == "Refurbished"
    assert listing.url == "https://www.newegg.com/Apple-MacBook-Pro/p/N82E16834260006"
    assert listing.ram_gb == 128
    assert listing.storage_gb == 2048


def test_parse_single_item_missing_title_returns_none():
    scraper = make_scraper()
    html = '<div class="item-cell"><ul class="price"><li class="price-current">$<strong>100</strong></li></ul></div>'
    item = card_from_html(html).select_one(".item-cell")
    assert scraper._parse_single_item(item) is None


def test_parse_single_item_missing_price_returns_none():
    scraper = make_scraper()
    html = '<div class="item-cell"><a class="item-title" href="/x/p/1">Some MacBook Pro</a></div>'
    item = card_from_html(html).select_one(".item-cell")
    assert scraper._parse_single_item(item) is None
