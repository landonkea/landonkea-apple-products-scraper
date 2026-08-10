# ───────────────────────────────────────────────────────────────────
# Product type interface — the extension point for new categories
# ───────────────────────────────────────────────────────────────────
# WHAT: This file defines the contract every "product type" (a
# category of thing to search for — electronics, and eventually
# things like apparel) must implement.
#
# WHY THIS EXISTS: Everything about matching/scoring a listing used
# to be hardcoded for Apple hardware (chip names, RAM, screen size).
# That logic now lives in src/product_types/electronics.py as the
# first implementation of this interface, so the scraping pipeline
# itself (BaseScraper, PriceAnalyzer) no longer assumes "the thing
# being searched for has a chip and RAM" — it just asks whichever
# ProductTypeHandler is active.
#
# THIS PLAN HAS BEEN VALIDATED: src/product_types/apparel.py (boots)
# is a real second implementation, following exactly the steps below.
# It's registered in PRODUCT_TYPES but has no active `searches:` entry
# in config.yaml (see the commented-out example there and this file's
# module docstring) — it stays inert in production, but every layer
# of the plan below (steps 1-5) is exercised by
# tests/test_product_types_apparel.py, including a real
# get_enabled_scrapers() check proving step 4 needed zero code changes
# (the `applicable_product_types: [electronics]` sites were already
# pre-configured for exactly this scenario). Use apparel.py as the
# concrete reference alongside electronics.py when building a THIRD
# product type.
#
# HOW TO ADD A NEW PRODUCT TYPE (e.g. "apparel" for boots):
#   1. Create src/product_types/apparel.py implementing every method
#      below (use electronics.py as a structural reference — same
#      shape, different fields: size/brand/color instead of
#      chip/RAM/storage).
#   2. Register it in src/product_types/__init__.py's PRODUCT_TYPES
#      dict.
#   3. Add a `searches:` entry in config.yaml with
#      `product_type: apparel` and whatever spec fields your
#      passes_type_filters()/score_bonuses() actually read.
#   4. In config.yaml's `sites:`, add `applicable_product_types:
#      [electronics]` to any site that will never carry apparel
#      (Apple Refurb, BestBuy, Newegg, Gazelle) so they're
#      automatically skipped for an apparel search instead of
#      wasting a request. General marketplaces (eBay, Swappa,
#      Mercari, OfferUp, BackMarket) need no change — they already
#      build their queries from product_name alone.
#   5. eBay/Swappa/Mercari/OfferUp/BackMarket will search apparel for
#      free with just the config above. A site that ONLY sells boots
#      (e.g. Zappos, Nordstrom Rack) still needs its own scraper
#      written the same way src/scrapers/backmarket.py was — this
#      interface makes the matching/scoring pipeline reusable, not
#      the individual retailer integrations.
# ───────────────────────────────────────────────────────────────────

from abc import ABC, abstractmethod
from typing import Optional


class ProductTypeHandler(ABC):
    """
    Everything about matching and scoring a listing that varies by
    product category, in one place.

    BaseScraper.parse_common_specs() / passes_filters() and
    PriceAnalyzer._score_listing() call into whichever handler is
    registered for the active search's `product_type` — they never
    contain category-specific logic themselves.
    """

    @abstractmethod
    def parse_specs(self, title: str) -> dict:
        """
        Pull whatever structured fields matter for this product type
        out of a listing title (e.g. RAM/storage/chip for electronics;
        size/brand/color for apparel).

        Returns a dict. For electronics this is the same shape
        ScrapedListing already expects (ram_gb, storage_gb,
        screen_size, chip, cpu_cores, gpu_cores) so it drops in with
        zero changes to any scraper. A future type free to return
        whatever keys make sense for it.
        """
        raise NotImplementedError

    @abstractmethod
    def is_relevant(self, title: str, search, condition: Optional[str] = None) -> bool:
        """
        Reject accessories/off-topic listings before real spec
        matching even runs — e.g. a phone case that mentions the
        phone's name, or a "for parts" listing.

        `search` is the active SearchConfig — needed because which
        relevance rules apply can depend on what's being searched for
        (e.g. electronics uses different accessory keyword lists for
        "MacBook Pro" vs "iPhone" searches).
        """
        raise NotImplementedError

    @abstractmethod
    def passes_type_filters(self, listing, search) -> bool:
        """
        The category-specific portion of BaseScraper.passes_filters():
        does this listing's parsed specs actually match what the
        search is looking for (chip generation, RAM tier, screen size,
        storage range for electronics; size/brand for apparel, etc.).

        `listing` is a ScrapedListing, `search` is the active
        SearchConfig. Universal checks (price range floor/ceiling,
        location) stay in BaseScraper.passes_filters() itself and are
        NOT this method's job.
        """
        raise NotImplementedError

    @abstractmethod
    def score_bonuses(self, listing, search) -> float:
        """
        Category-specific additive bonus points for PriceAnalyzer's
        deal score (0 or negative if nothing applies). Universal
        factors (price-vs-median, the suspicious-price safeguard,
        general condition wording) stay in price_analyzer.py itself.

        `listing` is a database Listing row, `search` is the active
        SearchConfig.
        """
        raise NotImplementedError

    @abstractmethod
    def min_price_usd(self, search) -> float:
        """
        The floor below which a listing is almost certainly an
        accessory/part rather than the real product, for this
        category (e.g. $200 for a computer, $100 for a phone).
        """
        raise NotImplementedError
