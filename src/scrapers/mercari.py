# ─────────────────────────────────────────────────────────────────────
# Mercari scraper — fetches MacBook listings from Mercari Japan
# ─────────────────────────────────────────────────────────────────────
# Mercari is Japan's largest secondhand marketplace (like eBay Japan).
# MacBooks are often significantly cheaper on Mercari Japan due to
# the weaker Yen and different market conditions.
#
# WHY THIS IS USEFUL:
# Japanese Mercari often has MacBooks at prices 10-30% below US markets.
# Even with international shipping, these can be great deals.
#
# NOTE ON LANGUAGE:
# Mercari Japan's interface is primarily Japanese.  However, product
# titles for electronics are often in English (e.g. "MacBook Pro 14
# M3 Pro 2023 16GB 512GB").
#
# PARSING STRATEGY:
# 1. Search Mercari Japan with the configured product name.
# 2. Parse listing cards using data-testid attributes.
# 3. For chip info (M1/M2/M3/M4), we may need to fetch individual
#    detail pages because sellers often don't include chip names in
#    the listing title.
# ─────────────────────────────────────────────────────────────────────

import re
from typing import Optional
from urllib.parse import quote

from scrapers.base import BaseScraper, ScrapedListing
from config import Config


class MercariScraper(BaseScraper):
    """
    Scraper for Mercari Japan marketplace listings.

    CHALLENGES:
    - Mercari Japan uses client-side rendering, so Playwright is required.
    - Product titles may be in Japanese (we still parse specs from them).
    - Chip info (M1/M2/M3) is often missing from listing titles.
    - We may need to fetch individual detail pages for full specs.

    FALLBACK STRATEGY:
    1. Try Playwright first (handles JavaScript rendering).
    2. Fall back to plain HTTP requests if Playwright fails.
    """

    def __init__(self, config: Config):
        """
        Initialize the Mercari scraper.

        Args:
            config: Global configuration with search parameters.
        """
        super().__init__(config)
        self.source_name = "mercari"

    def _build_search_url(self, screen_size: Optional[int]) -> str:
        """
        Build a Mercari Japan search URL.

        Args:
            screen_size: Optional screen size to narrow the search.
                         e.g. 14 becomes "MacBook Pro 14inch".

        Returns:
            Full URL to Mercari Japan search results.
        """
        product = self.config.search.product_name
        if screen_size:
            # Include screen size in the query for more precise results.
            query = f"{product} {screen_size}inch"
        else:
            query = product
        # URL-encode the query for Japanese characters compatibility.
        encoded = quote(query)
        return f"https://jp.mercari.com/search?keyword={encoded}"

    def scrape(self) -> list[ScrapedListing]:
        """
        Main entry point: fetch and parse all Mercari listings.

        STRATEGY:
        1. Build search URLs for each configured screen size.
        2. Try fetching with Playwright (for JS-rendered content).
        3. Fall back to plain HTTP requests.
        4. Parse listing cards from the HTML.
        5. For listings missing chip info, fetch the detail page.
        6. Apply filters and deduplicate.

        Returns:
            List of ScrapedListing objects matching the search criteria.
        """
        found: list[ScrapedListing] = []
        found_ids: set = set()

        # Determine which screen sizes to search.
        screen_sizes = self.config.search.screen_sizes
        sizes_to_search = screen_sizes if screen_sizes else [None]

        for screen_size in sizes_to_search:
            url = self._build_search_url(screen_size)
            html = None

            # Try Playwright first, then fall back to plain HTTP.
            try:
                html = self.fetch_with_playwright(url)
            except Exception as e:
                print(f"  [Mercari] Playwright failed: {e}, trying plain request...")
                try:
                    html = self.fetch_page(url)
                except Exception as e2:
                    print(f"  [Mercari] Plain request also failed: {e2}")
                    continue

            if not html:
                continue
            soup = self.parse_html(html)

            # Try multiple CSS selectors for listing items.
            # Mercari's class names change frequently.
            cards = soup.select("li[data-testid='item-cell']")
            if not cards:
                cards = soup.select("a[data-testid='thumbnail-link']")

            results_for_size = 0
            max_results = self.config.search.results_per_size

            for card in cards:
                if results_for_size >= max_results:
                    break
                try:
                    listing = self._parse_card(card)
                    if listing and listing.listing_id not in found_ids:
                        if self.passes_filters(listing):
                            found.append(listing)
                            found_ids.add(listing.listing_id)
                            results_for_size += 1
                except Exception:
                    # Skip individual card parse errors.
                    continue

        print(f"  [Mercari] Found {len(found)} matching listings")
        return found

    def _parse_card(self, card) -> Optional[ScrapedListing]:
        """
        Extract listing data from a single Mercari listing card.

        Args:
            card: A BeautifulSoup element representing a listing card.

        Returns:
            A ScrapedListing object, or None if parsing fails.
        """
        # Extract the title from the thumbnail item name span.
        title_elem = card.select_one("span[data-testid='thumbnail-item-name']")
        if not title_elem:
            return None

        title = title_elem.get_text(strip=True)
        if not title:
            return None
        # Only process MacBook, iPad, or iPhone listings based on search config.
        product = self.config.search.product_name.lower()
        if "macbook" in product and "MacBook" not in title:
            return None
        elif "ipad" in product and "iPad" not in title:
            return None
        elif "iphone" in product and "iPhone" not in title:
            return None

        # Extract the price from the number span.
        price_amount = card.select_one("span.number__6b270ca7")
        if not price_amount:
            return None
        price_text = price_amount.get_text(strip=True)
        price_text = price_text.replace("$", "").replace(",", "")
        try:
            price = float(price_text)
        except ValueError:
            return None

        # Extract the listing URL from the thumbnail link.
        link_elem = card.select_one("a[data-testid='thumbnail-link']")
        url = ""
        if link_elem:
            url = link_elem.get("href", "")
            if url and not url.startswith("http"):
                url = f"https://jp.mercari.com{url}"

        # Extract a unique listing ID from the URL path.
        id_match = re.search(r'/(?:item|shops/product)/([^/]+)', url)
        listing_id = f"mercari_{id_match.group(1)}" if id_match else f"mercari_{abs(hash(url))}"

        # Mercari doesn't always show condition clearly.
        condition = None

        # Extract specs from the title string.
        specs = self.parse_common_specs(title)
        ram = specs["ram_gb"]
        storage = specs["storage_gb"]
        screen = specs["screen_size"]
        chip = specs["chip"]

        # Mercari sellers rarely put chip names in the listing title.
        # If chip wasn't found, fetch the detail page and look for
        # it in the description / page text.
        if not chip and url and "macbook pro" in title.lower():
            try:
                chip = self._extract_chip_from_detail(url)
            except Exception:
                pass

        # Last resort: high-price MacBook Pros are almost certainly
        # current-gen (M4/M5 Max).  Use the configured chip value.
        if not chip and "macbook pro" in title.lower() and price > 2000:
            chip = self.config.search.chip

        cpu_cores = specs["cpu_cores"]
        gpu_cores = specs["gpu_cores"]

        return ScrapedListing(
            source=self.source_name,
            listing_id=listing_id,
            title=title,
            price_usd=price,
            url=url,
            condition=condition,
            ram_gb=ram,
            storage_gb=storage,
            screen_size=screen,
            chip=chip,
            location=None,
            cpu_cores=cpu_cores,
            gpu_cores=gpu_cores,
        )

    def _extract_chip_from_detail(self, url: str) -> Optional[str]:
        """
        Fetch the Mercari item detail page and search for chip info
        in the description text (not just the title).

        WHY THIS IS NEEDED:
        Mercari sellers often list MacBooks without the chip name in
        the title (e.g. "MacBook Pro 14 2023 16GB").  The chip info
        is usually buried in the item description on the detail page.

        STRATEGY:
        1. Fetch the item detail page.
        2. Search the full page text for chip identifiers (M1, M2, M3, etc.).
        3. Also try specific description selectors for a more targeted search.

        Args:
            url: The full URL to the Mercari item detail page.

        Returns:
            Chip name string (e.g. "M3 Pro") or None if not found.
        """
        try:
            html = self.fetch_page(url)
        except Exception:
            return None
        soup = self.parse_html(html)
        # First, search the entire page text.
        page_text = soup.get_text(separator=" ", strip=True)
        chip = self.extract_chip(page_text)
        if chip:
            return chip

        # If not found, try specific description section selectors.
        desc_selectors = [
            "[class*='description' i]",
            "[data-testid*='description']",
            "meta[name='description']",
        ]
        for selector in desc_selectors:
            el = soup.select_one(selector)
            if el:
                text = (
                    el.get("content", "")
                    if el.name == "meta"
                    else el.get_text(separator=" ", strip=True)
                )
                chip = self.extract_chip(text)
                if chip:
                    return chip
        return None
