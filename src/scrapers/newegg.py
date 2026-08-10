# ─────────────────────────────────────────────────────────────────────
# Newegg scraper — fetches Refurbished/Used MacBook Pro (and, where
# available, iPhone) listings from newegg.com.
# ─────────────────────────────────────────────────────────────────────
# Newegg is a PC-hardware-focused electronics retailer that also runs
# a third-party marketplace for refurbished/used/open-box Apple gear.
# No login is required to browse or search.
#
# WHY PLAIN REQUESTS (NOT PLAYWRIGHT):
# Verified by live-fetching https://www.newegg.com/p/pl?d=MacBook+Pro
# with a plain `requests.get` (realistic desktop UA, no cookies/session
# warmup): HTTP 200, ~830KB HTML, and the listing grid (`.item-cell`,
# `.item-title`, `.price-current`, etc.) is fully present in the raw
# response — no JS rendering needed, unlike Best Buy/OfferUp. Newegg's
# search results are server-side rendered.
#
# WHY THE QUERY IS A BARE PRODUCT NAME, NOT "<product> + chip/model
# terms" (the eBay fix does NOT transfer here — verified, not assumed):
# eBay's `_build_search_url` docstring documents that a bare-name query
# sorted price-ascending buries real high-value listings behind 100+
# pages of accessories, fixed there by appending the tracked chip/
# generation terms as an OR-group. Trying the identical fix on Newegg
# (`d=MacBook+Pro+14-inch+M5+Max+M4+Max+M3+Max`) was tested live and
# backfires: Newegg's relevance ranking surfaces MacBook *case*
# listings first, because those case titles list every chip generation
# they fit ("Case for MacBook Pro 14 inch ... M5 M4 M3 M2 M1") and that
# becomes a stronger keyword match than a real listing that only
# mentions one chip. A narrower query like "MacBook Pro 14-inch" is
# also worse, not better — it was tested live and returns only 14
# results, most of them unrelated non-Apple 14" laptops (HP, Acer),
# because Newegg treats "14-inch" as a generic spec term.
#   The bare query "MacBook Pro" with NO sort param (Newegg's default
# relevance ranking, not price-ascending) was tested live across 4
# pages (~170 results) and stayed 80-100% real Apple MacBook Pro
# listings per page (9, 12, 5, and 0 non-matches out of 44/48/41/36),
# including real "M3 Max" listings on pages 2 and 4 ($2,050-$3,199).
# Passing `&Order=1` (Newegg's price-ascending sort, confirmed live —
# first result becomes a $12.99 SSD adapter, then $108-123 decade-old
# Intel MacBooks) reproduces the exact eBay bug, so it is deliberately
# NOT used here. `is_likely_macbook_pro()` (from base.py) mops up the
# remaining non-Apple/accessory noise.
#
# WHY IPHONE NEEDED NO SPECIAL-CASE (eBay's price-floor/storage-in-
# query fix does NOT need to transfer here — verified, not assumed):
# eBay's docstring explains iPhone accessory titles legitimately
# contain the full generation name ("Case for iPhone 15 Pro Max"),
# which made a bare query on eBay return 122/122 sub-$5 accessories on
# page 1. The identical bare query "iPhone Pro Max" was tested live
# against Newegg and did NOT reproduce that failure: of the first 15
# results, ~10 were real unlocked refurbished iPhones ($789-$1,184)
# and only a handful were cases/screen protectors — Newegg's relevance
# ranking already favors the phones. `is_likely_iphone()`'s existing
# accessory-keyword + storage-capacity checks are therefore sufficient
# without any extra price floor or storage term in the query string.
# Newegg does carry real iPhone Pro Max inventory — it is not a
# PC-only site in practice, at least for this product line.
#
# LISTING CARD STRUCTURE (from live HTML, not assumed):
#   <div class="item-cell">
#     <div class="item-container" id="<listing-id>">
#       <a class="item-title" href="https://www.newegg.com/.../p/...">
#         <span class="item-open-box-italic">Refurbished</span>
#         <actual title text>
#       </a>
#       <ul class="price">
#         <li class="price-current">$<strong>519</strong><sup>.99</sup></li>
#       </ul>
#
# Condition comes from the `item-open-box-italic` badge span, which
# in live data was always present for Apple laptops and read one of
# "Refurbished", "Used - Good", "Used - Very Good" (never blank).
# ─────────────────────────────────────────────────────────────────────

import re
from typing import Optional

from scrapers.base import BaseScraper, ScrapedListing
from config import Config


class NeweggScraper(BaseScraper):
    """
    Scraper for Newegg's Refurbished/Used Apple MacBook Pro and
    iPhone Pro Max listings.

    Newegg is a third-party marketplace mixed in with first-party
    PC-hardware retail, so `is_likely_macbook_pro()` / `is_likely_iphone()`
    (from base.py) are what actually keep non-Apple/accessory noise out
    — see the module docstring above for why the search query itself
    can't do all of that filtering (unlike the eBay scraper).
    """

    BASE_URL = "https://www.newegg.com/p/pl"
    MAX_PAGES = 5

    def __init__(self, config: Config):
        super().__init__(config)
        self.source_name = "newegg"

    def _build_search_url(self, page: int) -> str:
        """
        Build a Newegg search URL for the configured product.

        Deliberately a bare product-name query with NO sort param —
        see the module docstring for the live-tested reasoning.

        Args:
            page: 1-indexed page number.

        Returns:
            A Newegg search URL.
        """
        product = self.config.search.product_name
        query = product.replace(" ", "+")
        url = f"{self.BASE_URL}?d={query}"
        if page > 1:
            url += f"&page={page}"
        return url

    def _get_condition(self, item) -> Optional[str]:
        """
        Extract the condition badge text (e.g. "Refurbished",
        "Used - Good") from a listing card.

        Args:
            item: BeautifulSoup element for the product cell.

        Returns:
            The condition string, or None if no badge is present.
        """
        badge = item.select_one("span.item-open-box-italic")
        if badge:
            text = badge.get_text(strip=True)
            if text:
                return text
        return None

    def _get_listing_id(self, item, url: str) -> str:
        """
        Extract a unique listing ID.

        Newegg tags each product's outer container with its internal
        item number as the `id` attribute (e.g. "9SIA7WPKAR3575").
        Falls back to the `/p/<sku>` path segment in the URL, then a
        hash of the URL as a last resort.

        Args:
            item: BeautifulSoup element for the product cell.
            url: The listing's URL.

        Returns:
            A unique string identifier for this listing.
        """
        container = item.select_one(".item-container")
        if container and container.get("id"):
            return str(container["id"])
        match = re.search(r'/p/([^/?]+)', url)
        if match:
            return match.group(1)
        return f"url_{hash(url)}"

    def _get_price(self, item) -> Optional[float]:
        """
        Extract the current price from a listing card.

        Newegg splits the price into a `<strong>` (dollars) and a
        `<sup>` (cents) inside `li.price-current`, e.g.
        "$<strong>519</strong><sup>.99</sup>" -> 519.99.

        Args:
            item: BeautifulSoup element for the product cell.

        Returns:
            The price as a float, or None if it can't be parsed.
        """
        price_el = item.select_one("li.price-current")
        if not price_el:
            return None
        text = price_el.get_text(" ", strip=True)
        # text looks like "$ 519 .99 –" (a trailing "to" range marker
        # is present for multi-option listings; we only want the low
        # end, which is what price-current already shows).
        text = text.replace("$", "").replace(",", "")
        match = re.search(r'(\d+)\s*\.\s*(\d{2})', text)
        if match:
            return float(f"{match.group(1)}.{match.group(2)}")
        # Fallback: whole-dollar price with no cents shown.
        match = re.search(r'(\d+)', text)
        if match:
            return float(match.group(1))
        return None

    def _parse_single_item(self, item) -> Optional[ScrapedListing]:
        """
        Parse a single Newegg product cell into a ScrapedListing.

        Args:
            item: BeautifulSoup element representing a `.item-cell`.

        Returns:
            A ScrapedListing, or None if required fields are missing.
        """
        title_el = item.select_one("a.item-title")
        if not title_el:
            return None
        title = title_el.get_text(" ", strip=True)
        if not title:
            return None

        url = title_el.get("href", "")
        if not url:
            return None
        if url.startswith("/"):
            url = "https://www.newegg.com" + url

        price = self._get_price(item)
        if price is None:
            return None

        condition = self._get_condition(item)
        listing_id = self._get_listing_id(item, url)

        specs = self.parse_common_specs(title)

        return ScrapedListing(
            source=self.source_name,
            listing_id=listing_id,
            title=title,
            price_usd=price,
            url=url,
            condition=condition,
            ram_gb=specs["ram_gb"],
            storage_gb=specs["storage_gb"],
            screen_size=specs["screen_size"],
            chip=specs["chip"],
            location=None,
            cpu_cores=specs["cpu_cores"],
            gpu_cores=specs["gpu_cores"],
        )

    def _fetch_page_cards(self, page: int) -> list:
        """
        Fetch one Newegg search results page and return its listing
        cards (`.item-cell` elements).

        HOW: Builds the page URL, fetches it, and parses out every
        `.item-cell`. Both failure modes below intentionally return an
        empty list rather than raising, so the caller can treat "fetch
        failed" and "no more results" the same way (stop paginating) —
        that matches the original combined behavior of this scraper.

        WHY: Isolates the network+select step from the "loop over
        pages and collect listings" logic in scrape(), mirroring the
        per-slug/per-collection fetch split used in swappa.py /
        gazelle.py.

        Args:
            page: 1-indexed page number.

        Returns:
            A list of BeautifulSoup `.item-cell` elements. Empty if
            the fetch failed or the page has no more results.
        """
        url = self._build_search_url(page)
        try:
            html = self.fetch_page(url)
        except Exception as e:
            print(f"  [Newegg] Failed to fetch page {page}: {e}")
            return []

        soup = self.parse_html(html)
        # No more results (or blocked) if this comes back empty —
        # scrape() stops paginating either way.
        return soup.select(".item-cell")

    def _collect_from_cards(
        self,
        cards: list,
        found: list[ScrapedListing],
        found_ids: set,
        max_results: int,
    ) -> None:
        """
        Parse a page's listing cards into ScrapedListings, filter, and
        dedup them into `found`/`found_ids` in place.

        WHY IN-PLACE: scrape() needs to track total found-count and
        seen-ids across every page's cards, not just one page's — a
        shared mutable found/found_ids avoids re-threading that state
        through a return value on every call.

        Args:
            cards: BeautifulSoup `.item-cell` elements from one page.
            found: Accumulator list of accepted ScrapedListings so far.
            found_ids: Accumulator set of listing_ids already accepted.
            max_results: Stop once `found` reaches this length.
        """
        for item in cards:
            if len(found) >= max_results:
                break
            try:
                listing = self._parse_single_item(item)
                if listing and listing.listing_id not in found_ids:
                    if self.passes_filters(listing):
                        found.append(listing)
                        found_ids.add(listing.listing_id)
            except Exception:
                # Skip individual parse errors.
                continue

    def scrape(self) -> list[ScrapedListing]:
        """
        Main entry point: fetch and parse Newegg listings for the
        configured product.

        STRATEGY:
        A single bare-product-name query (no per-screen-size query
        variants, unlike bestbuy.py) — see the module docstring for
        why appending screen-size/chip terms to the query actively
        hurts result quality on Newegg. Screen size and chip filtering
        happen post-parse via `passes_filters()` instead, same as
        every other field.

        Paginates up to MAX_PAGES pages (Newegg's default relevance
        sort, no price sort — see module docstring) or until
        `results_per_size` matches are collected, whichever comes
        first.

        Returns:
            List of ScrapedListing objects matching the search criteria.
        """
        found: list[ScrapedListing] = []
        found_ids: set = set()
        max_results = self.config.search.results_per_size

        for page in range(1, self.MAX_PAGES + 1):
            if len(found) >= max_results:
                break

            cards = self._fetch_page_cards(page)
            if not cards:
                break

            self._collect_from_cards(cards, found, found_ids, max_results)

        print(f"  [Newegg] Found {len(found)} matching listings")
        return found
