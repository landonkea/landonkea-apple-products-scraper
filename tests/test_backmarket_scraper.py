# ───────────────────────────────────────────────────────────────────
# Tests for the Back Market scraper's parsing/transformation helpers
# (src/scrapers/backmarket.py)
# ───────────────────────────────────────────────────────────────────
# Network-free unit tests: they exercise only the pure functions/
# methods that turn already-fetched HTML/JSON into raw offer dicts
# (and raw dicts into ScrapedListing objects). The network-calling
# scrape()/_fetch_with_fallback() methods are intentionally NOT
# tested here — see test_gazelle_scraper.py's module docstring for
# why (needs live HTTP/Playwright access).
#
# HOW TO RUN:
#   pytest tests/test_backmarket_scraper.py -v
# ───────────────────────────────────────────────────────────────────

import json
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bs4 import BeautifulSoup

from scrapers.backmarket import BackMarketScraper


def make_scraper(product_name="MacBook Pro"):
    """
    Build a BackMarketScraper wired to a minimal fake config.

    WHY A FAKE CONFIG: the methods under test here (slug/title
    conversion, tile discovery, offer extraction) only ever read
    self.config.search.product_name — a full real Config object
    would need the entire dataclass tree built out for no benefit.
    """
    fake_search = SimpleNamespace(product_name=product_name)
    fake_config = SimpleNamespace(search=fake_search)
    return BackMarketScraper(fake_config)


# ── _slug_to_title ──────────────────────────────────────────────────

def test_slug_to_title_normalizes_storage_and_screen_size():
    scraper = make_scraper()
    title = scraper._slug_to_title(
        "macbook-pro-2023-142-inch-m3-8-core-and-10-core-gpu-8gb-ram-ssd-1000gb"
    )
    # "142-inch" -> "14.2-inch" (dropped decimal restored)
    assert "14.2 inch" in title.lower()
    # "-ssd-1000gb" -> "-ssd-1tb" (round-thousand GB restored to TB)
    assert "1TB" in title
    assert "1000GB" not in title


def test_slug_to_title_uppercases_abbreviations_and_capitalizes():
    scraper = make_scraper()
    title = scraper._slug_to_title("macbook-pro-m4-16gb-ram-ssd-512gb")
    assert title.startswith("Macbook")
    assert "16GB RAM" in title
    assert "SSD 512GB" in title


def test_slug_to_title_uses_only_last_path_segment():
    scraper = make_scraper()
    title = scraper._slug_to_title(
        "https://www.backmarket.com/en-us/p/macbook-pro-m3-16gb-512gb/abc-123"
    )
    # The trailing UUID segment, not the slug, would be last here --
    # confirm it still finds a real slug rather than choking on it.
    assert "abc 123" in title.lower() or "Abc" in title


# ── _discover_generation_links ──────────────────────────────────────

MACBOOK_SEARCH_HTML = """
<html><body>
<article data-spec="product-card-content">
  <span data-testid="product-title">MacBook Pro (M5 series)</span>
  <h3><a href="/en-us/p/macbook-pro-2025-14-inch-m5/uuid-1?l=12">link</a></h3>
</article>
<article data-spec="product-card-content">
  <span data-testid="product-title">MacBook Pro (M4 series)</span>
  <h3><a href="/en-us/p/macbook-pro-2024-14-inch-m4/uuid-2">link</a></h3>
</article>
<article data-spec="product-card-content">
  <span data-testid="product-title">iPad Pro 11-inch (M4 series)</span>
  <h3><a href="/en-us/p/ipad-pro-11/uuid-3">link</a></h3>
</article>
</body></html>
"""


def test_discover_generation_links_finds_product_pages():
    scraper = make_scraper(product_name="MacBook Pro")
    soup = BeautifulSoup(MACBOOK_SEARCH_HTML, "lxml")
    links = scraper._discover_generation_links(soup)
    assert len(links) == 2
    assert all(l.startswith("https://www.backmarket.com") for l in links)


def test_discover_generation_links_excludes_off_topic_tiles():
    # The keyword gate only requires "macbook pro" to appear in the
    # tile's title -- it excludes clearly unrelated product lines
    # (like an iPad tile on the same page) but is NOT an accessory
    # filter: a tile titled e.g. "MacBook Pro Sleeve Case" would still
    # pass this gate, since it does mention "macbook pro". Real
    # accessory rejection happens downstream in passes_filters()/
    # is_likely_macbook_pro(), same as every other scraper.
    scraper = make_scraper(product_name="MacBook Pro")
    soup = BeautifulSoup(MACBOOK_SEARCH_HTML, "lxml")
    links = scraper._discover_generation_links(soup)
    assert not any("ipad" in l for l in links)


def test_discover_generation_links_strips_tracking_params():
    scraper = make_scraper(product_name="MacBook Pro")
    soup = BeautifulSoup(MACBOOK_SEARCH_HTML, "lxml")
    links = scraper._discover_generation_links(soup)
    assert any(l.endswith("uuid-1") for l in links)  # "?l=12" stripped


def test_discover_generation_links_dedupes():
    # Dedup is keyed on the full URL, so give both tiles the exact
    # same href (e.g. discovered via both a 14" and 16" search).
    html = MACBOOK_SEARCH_HTML.replace(
        "/en-us/p/macbook-pro-2024-14-inch-m4/uuid-2",
        "/en-us/p/macbook-pro-2025-14-inch-m5/uuid-1",
    )
    scraper = make_scraper(product_name="MacBook Pro")
    soup = BeautifulSoup(html, "lxml")
    links = scraper._discover_generation_links(soup)
    assert len(links) == 1


def test_discover_generation_links_empty_page_returns_empty_list():
    scraper = make_scraper(product_name="MacBook Pro")
    soup = BeautifulSoup("<html><body></body></html>", "lxml")
    assert scraper._discover_generation_links(soup) == []


# ── _extract_variant_offers ─────────────────────────────────────────

def _build_nuxt_html(data: list) -> str:
    """Wrap a synthetic Nuxt payload array in the script tag the scraper looks for."""
    return f'<html><body><script id="__NUXT_DATA__">{json.dumps(data)}</script></body></html>'


def test_extract_variant_offers_resolves_indexed_references():
    # Nuxt's compact array format: dict fields hold indices into `data`
    # rather than inline values. Index 9 is the picker "item" the
    # scraper looks for (has label/productId/price/slug/parameters).
    data = [
        None,                                                    # 0: unused
        "iPhone 16 Pro Max 256GB",                                # 1: label
        "prod-abc-123",                                           # 2: productId
        {"amount": 4},                                            # 3: price (amount -> idx 4)
        899.0,                                                    # 4: amount value
        "iphone-16-pro-max-256gb-black-titanium-unlocked",        # 5: slug
        {"grade": 7},                                             # 6: parameters (grade -> idx 7)
        {"name": 8},                                              # 7: grade (name -> idx 8)
        "Good",                                                   # 8: condition name
        {"label": 1, "productId": 2, "price": 3, "slug": 5, "parameters": 6},  # 9: the item
    ]
    scraper = make_scraper()
    offers = scraper._extract_variant_offers(_build_nuxt_html(data))
    assert len(offers) == 1
    assert offers[0] == {
        "product_id": "prod-abc-123",
        "slug": "iphone-16-pro-max-256gb-black-titanium-unlocked",
        "price": 899.0,
        "condition": "Good",
    }


def test_extract_variant_offers_finds_multiple_sibling_variants():
    # Two picker items sharing most of the payload but different
    # productId/price/condition/slug -- e.g. two condition grades of
    # the same config, which is exactly what makes this page useful.
    data = [
        None,
        "iPhone 16 Pro Max 256GB",     # 1: label (shared)
        "prod-fair",                    # 2: productId (variant A)
        {"amount": 4}, 699.0,           # 3, 4: price (variant A)
        "iphone-16-pro-max-256gb-a",    # 5: slug (variant A)
        {"grade": 7}, {"name": 8}, "Fair",  # 6, 7, 8: condition (variant A)
        {"label": 1, "productId": 2, "price": 3, "slug": 5, "parameters": 6},  # 9: item A
        "prod-premium",                 # 10: productId (variant B)
        {"amount": 12}, 899.0,          # 11, 12: price (variant B)
        "iphone-16-pro-max-256gb-b",     # 13: slug (variant B)
        {"grade": 15}, {"name": 16}, "Premium",  # 14, 15, 16: condition (variant B)
        {"label": 1, "productId": 10, "price": 11, "slug": 13, "parameters": 14},  # 17: item B
    ]
    scraper = make_scraper()
    offers = scraper._extract_variant_offers(_build_nuxt_html(data))
    conditions = {o["condition"] for o in offers}
    assert conditions == {"Fair", "Premium"}


def test_extract_variant_offers_defaults_condition_when_grade_missing():
    data = [
        None,
        "iPhone 16 Pro Max 256GB",
        "prod-xyz",
        {"amount": 4}, 799.0,
        "iphone-16-pro-max-256gb",
        {},  # parameters with no "grade" key
        {"label": 1, "productId": 2, "price": 3, "slug": 5, "parameters": 6},
    ]
    scraper = make_scraper()
    offers = scraper._extract_variant_offers(_build_nuxt_html(data))
    assert offers[0]["condition"] == "Refurbished"


def test_extract_variant_offers_no_script_tag_returns_empty():
    scraper = make_scraper()
    html = "<html><body><p>no nuxt data here</p></body></html>"
    assert scraper._extract_variant_offers(html) == []


def test_extract_variant_offers_malformed_json_returns_empty():
    scraper = make_scraper()
    html = '<html><body><script id="__NUXT_DATA__">not valid json</script></body></html>'
    assert scraper._extract_variant_offers(html) == []


def test_extract_variant_offers_skips_incomplete_items():
    # Missing "slug" -- required_keys check should reject this entry
    # rather than crash on a KeyError.
    data = [
        None,
        "label",
        "prod-1",
        {"amount": 4}, 500.0,
        {"label": 1, "productId": 2, "price": 3, "parameters": None},
    ]
    scraper = make_scraper()
    assert scraper._extract_variant_offers(_build_nuxt_html(data)) == []


# ── _offer_to_listing ────────────────────────────────────────────────

def test_offer_to_listing_builds_scraped_listing():
    scraper = make_scraper()
    offer = {
        "product_id": "prod-abc-123",
        "slug": "iphone-16-pro-max-1000gb-black-titanium-unlocked",
        "price": 899.0,
        "condition": "Good",
    }
    listing = scraper._offer_to_listing(offer)
    assert listing is not None
    assert listing.price_usd == 899.0
    assert listing.condition == "Good"
    assert listing.storage_gb == 1024  # "1000gb" slug normalized to 1TB
    assert "prod-abc-123" in listing.url
    assert listing.listing_id == "bm_prod-abc-123_Good"


def test_offer_to_listing_returns_none_without_slug():
    scraper = make_scraper()
    offer = {"product_id": "prod-1", "slug": "", "price": 100.0, "condition": "Fair"}
    assert scraper._offer_to_listing(offer) is None


def test_offer_to_listing_distinguishes_same_product_different_condition():
    scraper = make_scraper()
    base = {"product_id": "prod-1", "slug": "macbook-pro-m4-512gb", "price": 900.0}
    fair = scraper._offer_to_listing({**base, "condition": "Fair"})
    premium = scraper._offer_to_listing({**base, "condition": "Premium"})
    assert fair.listing_id != premium.listing_id
