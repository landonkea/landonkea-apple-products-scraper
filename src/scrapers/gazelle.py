# ───────────────────────────────────────────────────────────────────
# Gazelle scraper — fetches listings from gazelle.com
# ───────────────────────────────────────────────────────────────────
# Gazelle is a used-electronics reseller (similar business model to
# Swappa — no login required to browse/search).
#
# LIVE-TESTING FINDINGS (this is what the code below is built on —
# do not "fix" this scraper based on assumptions without re-checking
# these against the real site first):
#
#   1. www.gazelle.com is a marketing/landing shell. The actual store
#      (and every route that matters — /collections/*, /products/*,
#      /search*) lives on a DIFFERENT hostname: buy.gazelle.com. A
#      request to www.gazelle.com/collections/... or .../products.json
#      404s even though the same path on buy.gazelle.com returns 200.
#      Confirmed via `curl -L` against both hosts.
#
#   2. buy.gazelle.com is a stock Shopify storefront (theme id visible
#      in asset URLs, standard Shopify JSON endpoints all respond).
#      That means it exposes Shopify's public JSON APIs directly —
#      no HTML scraping or JS rendering needed at all:
#        - GET /collections/{handle}/products.json?limit=250
#          Returns every product in a named collection, each with a
#          `variants` array giving price, availability, and the
#          option values (color / condition) per SKU. This is the
#          richest source — use it whenever a collection handle is
#          known.
#        - GET /search/suggest.json?q={query}&resources[type]=product
#          Site-wide predictive search. Product-level only (no
#          per-condition variant breakdown), but works for any query
#          string, including product types the site doesn't stock
#          (returns an empty products list rather than an error).
#      fetch_page() (plain requests, no Playwright) works fine for
#      both — no 403s, no bot-challenge page, confirmed via curl with
#      a plain desktop UA and zero cookies/session warm-up.
#
#   3. GAZELLE DOES NOT SELL MACBOOKS. Checked exhaustively:
#      /products.json?limit=250 (both pages, ~500 products total)
#      only ever has product_type "Cell Phones" or "iPads" — never a
#      laptop category. /search/suggest.json?q=macbook returns
#      `{"resources":{"results":{"products":[]}}}` — a genuine empty
#      catalog result, not a bug or a bot block. Gazelle's own nav
#      menu (scraped from the homepage) lists only iPhone/iPad/Google
#      Phone/Samsung Galaxy collections — no Mac category exists to
#      link to. So for the "MacBook Pro" search, 0 results is the
#      correct, verified answer *today*. The code below still runs a
#      real site-wide search for it (rather than hardcoding "return
#      []") so that if Gazelle ever starts stocking Macs, this
#      scraper picks them up automatically with no code change.
#
#   4. For iPhone Pro Max, Gazelle DOES have real inventory, split
#      into one collection per generation, named exactly
#      `iphone-{N}-pro-max` (verified for N=15, 16, 17 — all 200 OK).
#      Each collection's products.json has one Shopify "product" per
#      storage+carrier combo (e.g. "iPhone 17 Pro Max 256GB
#      (Unlocked)"), and each product has one variant per
#      color x condition (Fair / Good / Excellent) with its own price
#      and `available` flag. Most variants are sold out at any given
#      time (`available: false`) — e.g. a live check of the 15/16/17
#      Pro Max collections combined found only ONE available 1TB+
#      variant across all three generations (a 16 Pro Max 1TB, Fair
#      condition, $927.99). That's expected scarcity, not a bug —
#      unavailable variants must be filtered out since they can't
#      actually be bought.
# ───────────────────────────────────────────────────────────────────

import re
from typing import Optional

from scrapers.base import BaseScraper, ScrapedListing
from config import Config


def _slugify(text: str) -> str:
    """
    Turn a human-readable name into a Shopify-style URL slug.

    e.g. "iPhone 17 Pro Max" -> "iphone-17-pro-max"

    Shopify collection/product handles are lowercase, space-and-most-
    punctuation-replaced-with-hyphens. This mirrors the exact handle
    format confirmed live for Gazelle's iPhone Pro Max collections.
    """
    slug = text.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


class GazelleScraper(BaseScraper):
    """
    Scraper for Gazelle (buy.gazelle.com) marketplace listings.

    STRATEGY:
    - If the search has `model_keywords` (e.g. iPhone Pro Max — see
      config.yaml's generation expansion), each keyword names a real
      Gazelle generation ("iPhone 17 Pro Max") that maps directly to
      a collection handle ("iphone-17-pro-max"). Fetch each
      collection's products.json and flatten every available
      variant into a listing.
    - Otherwise (e.g. MacBook Pro, which Gazelle doesn't currently
      stock — see module docstring), fall back to the site-wide
      predictive-search JSON endpoint so the scraper still does a
      real search rather than assuming there's nothing to find.
    """

    # The real storefront host — see module docstring point 1.
    # www.gazelle.com 404s on every route this scraper needs.
    BASE_URL = "https://buy.gazelle.com"

    def __init__(self, config: Config):
        super().__init__(config)
        self.source_name = "gazelle"

    # ── Collection-based path (iPhone Pro Max, etc.) ────────────
    def _collection_handles(self) -> list[str]:
        """
        Build Gazelle collection handles from the search's model
        keywords (e.g. ["iPhone 17 Pro Max", "iPhone 16 Pro Max",
        "iPhone 15 Pro Max"] -> ["iphone-17-pro-max", ...]).

        Returns an empty list if the search has no model_keywords
        (e.g. chip-based searches like MacBook Pro), signaling the
        caller to use the site-search fallback instead.
        """
        return [_slugify(kw) for kw in self.config.search.model_keywords]

    def _fetch_collection_products(self, handle: str) -> list[dict]:
        """
        Fetch every product in one Gazelle collection and flatten its
        available variants into raw listing dicts.

        WHY PER-COLLECTION: Gazelle (like Swappa) has no single
        endpoint returning all generations at once — each generation
        is its own collection. This mirrors swappa.py's
        _fetch_listings_for_slug() pattern: isolate the per-collection
        fetch so one failing/missing generation doesn't break the
        others.

        Returns a list of raw dicts with keys: title, price, url,
        condition, listing_id, location, ram_gb, storage_gb, chip.
        Only variants with available == True are included, since
        sold-out variants can't actually be purchased.
        """
        url = f"{self.BASE_URL}/collections/{handle}/products.json?limit=250"
        try:
            import json
            raw = self.fetch_page(url)
            data = json.loads(raw)
        except Exception as e:
            print(f"  [Gazelle] Error fetching collection {handle}: {e}")
            return []

        listings: list[dict] = []
        for product in data.get("products", []):
            product_title = product.get("title", "")
            handle_path = product.get("handle", "")
            for variant in product.get("variants", []):
                if not variant.get("available"):
                    continue
                price = variant.get("price")
                if price is None:
                    continue
                # option1 = color, option2 = condition (Fair/Good/Excellent)
                # on every Gazelle product checked — but fall back to
                # the variant's own title if that ever changes shape.
                condition = variant.get("option2") or variant.get("title")
                color = variant.get("option1")
                title_parts = [product_title]
                if color:
                    title_parts.append(color)
                if condition:
                    title_parts.append(condition)
                full_title = " - ".join(title_parts)

                variant_id = variant.get("id")
                listings.append({
                    "title": full_title,
                    "price": price,
                    "url": f"{self.BASE_URL}/products/{handle_path}?variant={variant_id}",
                    "condition": condition,
                    "listing_id": f"gazelle-{variant_id}",
                    "location": None,
                })
        return listings

    # ── Site-search fallback path (products with no known handle) ──
    def _fetch_search_products(self, query: str) -> list[dict]:
        """
        Fetch listings via Gazelle's site-wide predictive-search JSON
        endpoint (/search/suggest.json).

        WHY: Used for searches with no model_keywords (i.e. no known
        collection-handle naming scheme, like MacBook Pro). Also acts
        as this scraper's future-proofing: if Gazelle starts stocking
        a new product line, a plain keyword search still finds it
        without needing a code change to add a collection-handle map.

        NOTE: unlike the collection endpoint, this one is product-
        level, not variant-level (no per-condition breakdown), and
        gives a single "available" flag + price_min for the whole
        product. That's fine here since — per the live-tested finding
        in the module docstring — this path currently returns zero
        results for MacBook Pro; there's no real per-condition data
        to lose.
        """
        import json
        from urllib.parse import quote

        url = (
            f"{self.BASE_URL}/search/suggest.json?q={quote(query)}"
            f"&resources[type]=product&resources[limit]=50"
        )
        try:
            raw = self.fetch_page(url)
            data = json.loads(raw)
        except Exception as e:
            print(f"  [Gazelle] Error searching '{query}': {e}")
            return []

        listings: list[dict] = []
        products = data.get("resources", {}).get("results", {}).get("products", [])
        for product in products:
            if not product.get("available"):
                continue
            price = product.get("price_min") or product.get("price")
            if price is None:
                continue
            product_url = product.get("url", "")
            if product_url and not product_url.startswith("http"):
                product_url = f"{self.BASE_URL}{product_url}"
            listings.append({
                "title": product.get("title", ""),
                "price": price,
                "url": product_url,
                "condition": None,
                "listing_id": f"gazelle-{product.get('id')}",
                "location": None,
            })
        return listings

    def _parse_item(self, item: dict) -> Optional[ScrapedListing]:
        """
        Convert a raw listing dict into a ScrapedListing dataclass,
        parsing specs (RAM/storage/screen/chip/cores) out of the
        title via the shared base-class helper.
        """
        title = item.get("title", "")
        if not title:
            return None

        try:
            price = float(item["price"])
        except (KeyError, TypeError, ValueError):
            return None

        specs = self.parse_common_specs(title)

        return ScrapedListing(
            source=self.source_name,
            listing_id=item.get("listing_id", str(hash(title))),
            title=title,
            price_usd=price,
            url=item.get("url", ""),
            condition=item.get("condition"),
            ram_gb=specs["ram_gb"],
            storage_gb=specs["storage_gb"],
            screen_size=specs["screen_size"],
            chip=specs["chip"],
            location=item.get("location"),
            cpu_cores=specs["cpu_cores"],
            gpu_cores=specs["gpu_cores"],
        )

    def scrape(self) -> list[ScrapedListing]:
        """
        Main entry point: fetch and parse all Gazelle listings for the
        active search.

        1. If the search has model_keywords (e.g. iPhone Pro Max),
           fetch the matching per-generation collections.
        2. Otherwise, fall back to a site-wide search per chip option
           (or the bare product name if there are no chip options).
        3. Convert to ScrapedListing objects and apply passes_filters().
        4. Deduplicate by listing_id.
        """
        found: list[ScrapedListing] = []
        found_ids: set = set()

        raw_listings: list[dict] = []

        handles = self._collection_handles()
        if handles:
            for handle in handles:
                raw_listings.extend(self._fetch_collection_products(handle))
        else:
            # No known collection-handle scheme for this product
            # (e.g. MacBook Pro) — fall back to site-wide search,
            # one query per tracked chip generation if configured,
            # otherwise a single bare product-name query.
            product = self.config.search.product_name
            queries = (
                [f"{product} {opt}" for opt in self.config.search.chip_options]
                if self.config.search.chip_options
                else [product]
            )
            for query in queries:
                raw_listings.extend(self._fetch_search_products(query))

        for item in raw_listings:
            try:
                listing = self._parse_item(item)
                if listing and listing.listing_id not in found_ids:
                    if self.passes_filters(listing):
                        found.append(listing)
                        found_ids.add(listing.listing_id)
            except Exception:
                # Skip individual listing parse errors — don't fail the whole batch.
                continue

        print(f"  [Gazelle] Found {len(found)} matching listings")
        return found
