# ───────────────────────────────────────────────────────────────────
# OfferUp scraper — uses Playwright + extracts data from Next.js
# ───────────────────────────────────────────────────────────────────
# OfferUp is a peer-to-peer marketplace (like Craigslist but
# mobile-first).  Good for finding local deals on used MacBooks.
#
# CHALLENGE: OfferUp is a React app with strong anti-bot protection.
# Simple requests get blocked.  Even headless Playwright Chromium
# gets detected and served a stripped-down page.
#
# SOLUTION: Playwright loads the page, triggers JS execution, and
# we extract listing data from Next.js's __NEXT_DATA__ embedded JSON.
# This embedded data IS populated before the anti-bot blocks things.
#
# Why this is free:
#   - Playwright + Chromium runs on GitHub Actions free tier
#   - No paid proxy or rendering service needed
#   - ~10-15 seconds per page (slower than simple HTTP but works)
# ───────────────────────────────────────────────────────────────────

import json
import re
from typing import Optional

from scrapers.base import BaseScraper, ScrapedListing
from config import Config


class OfferUpScraper(BaseScraper):
    """
    Scrapes OfferUp for MacBook Pro M5 Max listings.
    
    Uses Playwright (headless Chromium) to load the JavaScript-
    heavy search page, then extracts listing data from the
    __NEXT_DATA__ embedded JSON.
    """
    
    def __init__(self, config: Config):
        """Initialize the OfferUp scraper."""
        super().__init__(config)
        self.source_name = "offerup"
    
    def _build_search_url(self, screen_size: Optional[int]) -> str:
        """
        Build an OfferUp search URL.
        
        Args:
            screen_size: Screen size in inches (14 or 16), or None for products without screen sizes.
        
        Returns:
            An OfferUp search URL.
        """
        product = self.config.search.product_name
        
        if screen_size:
            query = f"{product} {screen_size}-inch"
        else:
            query = product
        encoded = query.replace(" ", "+")
        
        return f"https://offerup.com/search/?q={encoded}"
    
    def _fetch_listings_json(self, url: str) -> list[dict]:
        """
        Load the OfferUp search page and extract listing data from
        the embedded Next.js state (__NEXT_DATA__).
        
        Playwright renders the page, then we extract the JSON data
        that Next.js embeds in a <script> tag.  This data contains
        all the listings the page would show, even if the visual
        render is blocked by anti-bot.
        
        Args:
            url: The OfferUp search URL.
        
        Returns:
            A list of listing dicts from the search results.
        """
        from playwright.sync_api import sync_playwright
        
        urls_to_try = [url]
        
        product = self.config.search.product_name
        chip = self.config.search.chip
        ram = self.config.search.ram_gb_primary
        specific_query = product
        if chip:
            specific_query += f" {chip}"
        if ram:
            specific_query += f" {ram}GB"
        fallback_url = f"https://offerup.com/search/?q={specific_query.replace(' ', '+')}"
        urls_to_try.append(fallback_url)
        
        next_data_json = None
        last_error = None
        
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox"],
                )
                
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US",
                )
                
                page = context.new_page()
                
                for i, try_url in enumerate(urls_to_try):
                    if i > 0:
                        print(f"  [OfferUp] Trying fallback URL: {try_url[:80]}")
                    
                    page.goto(try_url, wait_until="load", timeout=30000)
                    page.wait_for_timeout(5000)
                    
                    next_data_json = page.evaluate("""
                        () => {
                            const el = document.getElementById('__NEXT_DATA__');
                            return el ? el.textContent : null;
                        }
                    """)
                    
                    if next_data_json:
                        break
                
                browser.close()
        
        except Exception as e:
            last_error = e
        
        if last_error:
            raise Exception(
                f"Playwright error: {last_error}. "
                f"Install: pip install playwright && playwright install chromium"
            ) from last_error
        
        if not next_data_json:
            print("  [OfferUp] No __NEXT_DATA__ found on page")
            return []
        
        # ── Parse the JSON and extract listings ─────────
        data = json.loads(next_data_json)
        
        # Navigate through the Next.js data structure
        page_props = data.get("props", {}).get("pageProps", {})
        feed = page_props.get("searchFeedResponse", {})
        loose_tiles = feed.get("looseTiles", [])
        
        # Filter for listing tiles (not ads)
        listings = []
        for tile in loose_tiles:
            if tile.get("__typename") == "ModularFeedTileListing":
                listing_data = tile.get("listing", {})
                if listing_data and listing_data.get("title"):
                    listings.append(listing_data)
        
        return listings
    
    def _parse_listing(self, item: dict) -> Optional[ScrapedListing]:
        """
        Convert an OfferUp listing dict into a ScrapedListing.
        
        The listing dict comes from the __NEXT_DATA__ JSON and
        contains fields like:
          - listingId (UUID string)
          - title
          - price (string, e.g. "3998.89")
          - conditionText
          - locationName
          - image (object with url)
        
        Args:
            item: A listing dict from OfferUp's Next.js state.
        
        Returns:
            A ScrapedListing or None if it doesn't match.
        """
        # ── Title ───────────────────────────────────────────────
        title = item.get("title", "")
        if not title or "MacBook" not in title:
            return None
        
        # ── Price ───────────────────────────────────────────────
        price_str = item.get("price", "0")
        if isinstance(price_str, str):
            price_str = price_str.replace("$", "").replace(",", "")
        try:
            price = float(price_str)
        except (ValueError, TypeError):
            return None
        
        if price <= 0:
            return None
        
        # ── Listing ID and URL ──────────────────────────────────
        listing_id = item.get("listingId", "")
        if not listing_id:
            return None
        
        # OfferUp URLs are constructed like:
        #   https://offerup.com/item/detail/{listingId}
        url = f"https://offerup.com/item/detail/{listing_id}"
        
        # ── Condition ───────────────────────────────────────────
        condition = item.get("conditionText")
        if not condition:
            title_lower = title.lower()
            if "new" in title_lower and "like new" not in title_lower:
                condition = "New"
            elif "like new" in title_lower:
                condition = "Like New"
            elif "open box" in title_lower:
                condition = "Open Box"
            else:
                condition = "Used"
        
        # ── Location ────────────────────────────────────────────
        location = item.get("locationName") or item.get("location", "")
        
        # ── Parse specs from title ──────────────────────────────
        ram = self.extract_ram(title)
        storage = self.extract_storage(title)
        screen = self.extract_screen(title)
        chip = self.extract_chip(title)
        
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
            location=location,
        )
    
    def scrape(self) -> list[ScrapedListing]:
        """
        Scrape OfferUp for MacBook Pro listings sorted by price.
        
        Uses Playwright + __NEXT_DATA__ extraction to bypass
        OfferUp's anti-bot protection.
        
        Returns:
            A list of ScrapedListing objects.
        """
        found: list[ScrapedListing] = []
        found_ids: set = set()
        
        screen_sizes = self.config.search.screen_sizes
        sizes_to_search = screen_sizes if screen_sizes else [None]
        
        for screen_size in sizes_to_search:
            search_url = self._build_search_url(screen_size)
            
            try:
                listings_data = self._fetch_listings_json(search_url)
                
                results_for_size = 0
                max_results = self.config.search.results_per_size
                
                for item in listings_data:
                    if results_for_size >= max_results:
                        break
                    try:
                        listing = self._parse_listing(item)
                        if listing and listing.listing_id not in found_ids:
                            if self.passes_filters(listing):
                                found.append(listing)
                                found_ids.add(listing.listing_id)
                                results_for_size += 1
                    except Exception:
                        continue
                
            except Exception as e:
                print(f"  [OfferUp] Error: {e}")
                continue
        
        if found:
            print(f"  [OfferUp] Found {len(found)} matching listings")
        else:
            print(
                "  [OfferUp] No matching listings found."
            )
        
        return found
