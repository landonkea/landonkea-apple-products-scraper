# ───────────────────────────────────────────────────────────────────
# Tests for the Gazelle scraper's parsing/transformation helpers
# (src/scrapers/gazelle.py)
# ───────────────────────────────────────────────────────────────────
# These are network-free unit tests: they exercise only the pure
# functions/methods that turn already-fetched JSON payloads into raw
# listing dicts (and raw dicts into ScrapedListing objects). The
# network-calling scrape() method itself is intentionally NOT tested
# here — see the module docstring in test_scrapers.py's neighboring
# files for why (needs live HTTP access).
#
# HOW TO RUN:
#   pytest tests/test_gazelle_scraper.py -v
# ───────────────────────────────────────────────────────────────────

import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from scrapers.gazelle import GazelleScraper, _slugify


def make_scraper(product_name="MacBook Pro", chip_options=None, model_keywords=None):
    """
    Build a GazelleScraper wired to a minimal fake config.

    WHY A FAKE CONFIG: The methods under test here (variant/product
    flattening, item parsing, query building) never touch self.config
    except for the few fields explicitly read (product_name,
    chip_options, model_keywords) — a real Config object would need
    the entire dataclass tree built out for no benefit, so a
    SimpleNamespace covering just those fields is enough.
    """
    fake_search = SimpleNamespace(
        product_name=product_name,
        chip_options=chip_options or [],
        model_keywords=model_keywords or [],
    )
    fake_config = SimpleNamespace(search=fake_search)
    return GazelleScraper(fake_config)


def test_slugify():
    """Product/generation names turn into Shopify-style handles."""
    assert _slugify("iPhone 17 Pro Max") == "iphone-17-pro-max"
    assert _slugify("  MacBook Pro  ") == "macbook-pro"
    assert _slugify("M5 Max!!") == "m5-max"


def test_collection_handles_from_model_keywords():
    """model_keywords map straight onto slugified collection handles."""
    scraper = make_scraper(
        model_keywords=["iPhone 17 Pro Max", "iPhone 16 Pro Max"]
    )
    assert scraper._collection_handles() == [
        "iphone-17-pro-max",
        "iphone-16-pro-max",
    ]


def test_collection_handles_empty_when_no_model_keywords():
    """No model_keywords (e.g. MacBook Pro) means no known handles."""
    scraper = make_scraper(model_keywords=[])
    assert scraper._collection_handles() == []


def test_variant_to_listing_dict_skips_unavailable():
    """Sold-out variants (available: False) can't be bought, so they're dropped."""
    scraper = make_scraper()
    variant = {"id": 1, "price": "500.00", "available": False}
    assert scraper._variant_to_listing_dict("iPhone 17 Pro Max 256GB", "iphone-17", variant) is None


def test_variant_to_listing_dict_skips_missing_price():
    """A variant with no price can't be turned into a real listing."""
    scraper = make_scraper()
    variant = {"id": 1, "available": True}
    assert scraper._variant_to_listing_dict("iPhone 17 Pro Max 256GB", "iphone-17", variant) is None


def test_variant_to_listing_dict_builds_combined_title():
    """Title = product title + color (option1) + condition (option2)."""
    scraper = make_scraper()
    variant = {
        "id": 987,
        "price": "927.99",
        "available": True,
        "option1": "Black",
        "option2": "Fair",
    }
    listing = scraper._variant_to_listing_dict(
        "iPhone 16 Pro Max 1TB (Unlocked)", "iphone-16-pro-max-1tb", variant
    )
    assert listing == {
        "title": "iPhone 16 Pro Max 1TB (Unlocked) - Black - Fair",
        "price": "927.99",
        "url": "https://buy.gazelle.com/products/iphone-16-pro-max-1tb?variant=987",
        "condition": "Fair",
        "listing_id": "gazelle-987",
        "location": None,
    }


def test_variant_to_listing_dict_falls_back_to_variant_title():
    """If option2 is missing, condition falls back to the variant's own title."""
    scraper = make_scraper()
    variant = {"id": 5, "price": "100.00", "available": True, "title": "Default Title"}
    listing = scraper._variant_to_listing_dict("Widget", "widget", variant)
    assert listing["condition"] == "Default Title"
    assert listing["title"] == "Widget - Default Title"


def test_flatten_collection_products_filters_and_flattens():
    """
    Multiple products, each with multiple variants, flatten into one
    list containing only the available/priced variants.
    """
    scraper = make_scraper()
    data = {
        "products": [
            {
                "title": "iPhone 17 Pro Max 256GB",
                "handle": "iphone-17-pro-max-256gb",
                "variants": [
                    {"id": 1, "price": "999.00", "available": True, "option2": "Good"},
                    {"id": 2, "price": "899.00", "available": False, "option2": "Fair"},
                ],
            },
            {
                "title": "iPhone 17 Pro Max 512GB",
                "handle": "iphone-17-pro-max-512gb",
                "variants": [
                    {"id": 3, "price": None, "available": True, "option2": "Excellent"},
                ],
            },
        ]
    }
    listings = scraper._flatten_collection_products(data)
    assert len(listings) == 1
    assert listings[0]["listing_id"] == "gazelle-1"


def test_search_product_to_listing_dict_skips_unavailable():
    """Same availability rule applies on the site-search path."""
    scraper = make_scraper()
    product = {"id": 42, "price_min": "500.00", "available": False}
    assert scraper._search_product_to_listing_dict(product) is None


def test_search_product_to_listing_dict_prefixes_relative_url():
    """Relative product URLs get the buy.gazelle.com host prepended."""
    scraper = make_scraper()
    product = {
        "id": 42,
        "title": "iPhone 17 Pro Max",
        "price_min": "999.00",
        "available": True,
        "url": "/products/iphone-17-pro-max",
    }
    listing = scraper._search_product_to_listing_dict(product)
    assert listing["url"] == "https://buy.gazelle.com/products/iphone-17-pro-max"
    assert listing["listing_id"] == "gazelle-42"
    assert listing["condition"] is None


def test_flatten_search_products():
    """A search response's product list flattens, dropping unavailable entries."""
    scraper = make_scraper()
    data = {
        "resources": {
            "results": {
                "products": [
                    {"id": 1, "title": "A", "price_min": "100", "available": True, "url": "/a"},
                    {"id": 2, "title": "B", "price": "200", "available": False, "url": "/b"},
                ]
            }
        }
    }
    listings = scraper._flatten_search_products(data)
    assert len(listings) == 1
    assert listings[0]["listing_id"] == "gazelle-1"


def test_fallback_search_queries_with_chip_options():
    """One query per tracked chip generation when chip_options is set."""
    scraper = make_scraper(
        product_name="MacBook Pro", chip_options=["M5 Max", "M4 Max", "M3 Max"]
    )
    assert scraper._fallback_search_queries() == [
        "MacBook Pro M5 Max",
        "MacBook Pro M4 Max",
        "MacBook Pro M3 Max",
    ]


def test_fallback_search_queries_without_chip_options():
    """A single bare product-name query when no chip_options are configured."""
    scraper = make_scraper(product_name="MacBook Pro", chip_options=[])
    assert scraper._fallback_search_queries() == ["MacBook Pro"]


def test_parse_item_converts_raw_dict_to_scraped_listing():
    """_parse_item turns a raw dict into a ScrapedListing, parsing specs from the title."""
    scraper = make_scraper()
    item = {
        "title": "iPhone 16 Pro Max 1TB (Unlocked) - Black - Fair",
        "price": "927.99",
        "url": "https://buy.gazelle.com/products/x?variant=987",
        "condition": "Fair",
        "listing_id": "gazelle-987",
        "location": None,
    }
    listing = scraper._parse_item(item)
    assert listing is not None
    assert listing.source == "gazelle"
    assert listing.listing_id == "gazelle-987"
    assert listing.price_usd == 927.99
    assert listing.storage_gb == 1024


def test_parse_item_returns_none_for_missing_title():
    scraper = make_scraper()
    assert scraper._parse_item({"price": "100"}) is None


def test_parse_item_returns_none_for_invalid_price():
    scraper = make_scraper()
    assert scraper._parse_item({"title": "iPhone 17 Pro Max", "price": "not-a-number"}) is None
