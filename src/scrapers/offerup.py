# ───────────────────────────────────────────────────────────────────
# OfferUp scraper
# ───────────────────────────────────────────────────────────────────
# OfferUp is a peer-to-peer marketplace (like Craigslist but with
# a modern mobile-first interface).  Good for finding local deals
# on used MacBook Pros.
#
# CHALLENGE: OfferUp is FULLY JavaScript-rendered (React app).
# The HTML source of the search page is basically empty —
# just a <div id="root"> and some scripts.  Simple requests +
# BeautifulSoup CANNOT parse the listings.
#
# Our approach (tried in order):
#   1. Look for JSON-LD structured data in <script> tags
#      (OfferUp includes some for SEO purposes)
#   2. Try OfferUp's internal GraphQL/JSON API directly
#      (if they expose one for public searches)
#   3. If both fail, print a clear message that this site
#      needs a headless browser like Playwright
#
# To enable full OfferUp support in the future:
#   pip install playwright
#   playwright install chromium
# Then rewrite this scraper to use Playwright.
# ───────────────────────────────────────────────────────────────────

import json
import re
from typing import Optional
from urllib.parse import quote

from scrapers.base import BaseScraper, ScrapedListing
from config import Config


class OfferUpScraper(BaseScraper):
    """
    Scrapes OfferUp for MacBook Pro M5 Max listings.
    
    Uses multiple strategies to extract listing data from
    OfferUp's JavaScript-heavy pages.
    
    Strategy 1: JSON-LD (structured data in <script> tags).
    Strategy 2: Internal API endpoint.
    Strategy 3: Headless browser (future — requires Playwright).
    """
    
    def __init__(self, config: Config):
        """Initialize the OfferUp scraper."""
        super().__init__(config)
        self.source_name = "offerup"
    
    def _build_search_url(self, ram_gb: int) -> str:
        """
        Build an OfferUp search URL.
        
        OfferUp uses simple query parameter search:
          https://offerup.com/search/?q=macbook+pro+m5+max
        
        Args:
            ram_gb: RAM in GB (128 or 64).
        
        Returns:
            An OfferUp search URL.
        """
        product = self.config.search.product_name
        chip = self.config.search.chip
        screen = self.config.search.screen_size_inches
        
        query = f"{product} {screen}-inch {chip} {ram_gb}GB"
        encoded = quote(query)
        
        return f"https://offerup.com/search/?q={encoded}"
    
    def _parse_listing_id(self, item_id: str, url: str) -> str:
        """
        Extract the OfferUp item ID.
        
        OfferUp item IDs are in the URL path:
          https://offerup.com/item/detail/123456789
        
        Args:
            item_id: The item ID from JSON data (if available).
            url: The listing URL.
        
        Returns:
            A unique listing ID string.
        """
        if item_id:
            return str(item_id)
        
        # Try to extract from URL
        match = re.search(r'/item/detail/(\d+)', url)
        if match:
            return match.group(1)
        
        # Fallback: hash the URL
        return f"ou_{hash(url)}"
    
    def _try_jsonld(self, soup) -> list[dict]:
        """
        Try to extract listings from JSON-LD structured data.
        
        Many websites include JSON-LD <script> tags for SEO.
        OfferUp sometimes includes product data this way.
        
        Args:
            soup: A BeautifulSoup object of the search page.
        
        Returns:
            A list of listing dicts, or empty list if none found.
        """
        listings = []
        
        # Look for JSON-LD script tags
        scripts = soup.select("script[type='application/ld+json']")
        
        for script in scripts:
            try:
                data = json.loads(script.string)
                
                # Handle both single item and array formats
                if isinstance(data, dict):
                    data = [data]
                
                for item in data:
                    # JSON-LD for products has @type "Product"
                    if isinstance(item, dict):
                        item_type = item.get("@type", "")
                        if "Product" in item_type or "Item" in item_type:
                            listings.append(item)
            except (json.JSONDecodeError, AttributeError):
                continue
        
        return listings
    
    def _try_api(self, ram_gb: int) -> list[dict]:
        """
        Try to fetch listings from OfferUp's internal API.
        
        OfferUp's web app uses a JSON API to load search results.
        We try to call it directly with browser-like headers.
        
        Args:
            ram_gb: RAM in GB to search for.
        
        Returns:
            A list of listing dicts, or empty list if API fails.
        """
        product = self.config.search.product_name
        chip = self.config.search.chip
        screen = self.config.search.screen_size_inches
        
        query = f"{product} {screen}-inch {chip} {ram_gb}GB"
        
        # OfferUp API endpoints — try multiple known patterns
        api_urls = [
            # Direct JSON endpoint (known pattern)
            f"https://offerup.com/search/api/v1/items/search?q={quote(query)}&limit=50",
            # Alternative API path
            f"https://offerup.com/api/items/search?q={quote(query)}&limit=50",
        ]
        
        for api_url in api_urls:
            try:
                # Use API-specific headers
                headers = {
                    "Accept": "application/json, text/plain, */*",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": f"https://offerup.com/search/?q={quote(query)}",
                }
                
                response = self.session.get(api_url, headers=headers, timeout=15)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Try different response structures
                    if "items" in data:
                        return data["items"]
                    if "results" in data:
                        return data["results"]
                    if "listings" in data:
                        return data["listings"]
                    
                    # If we got an array at top level
                    if isinstance(data, list):
                        return data
                    
                    # If we got a dict with item keys
                    if isinstance(data, dict):
                        for key in ["data", "response", "search"]:
                            if key in data:
                                sub = data[key]
                                if isinstance(sub, list):
                                    return sub
                                if isinstance(sub, dict):
                                    items = sub.get("items", sub.get("results", sub.get("listings", [])))
                                    if items:
                                        return items
                
            except Exception:
                continue
        
        return []
    
    def _try_nextjs_data(self, soup) -> list[dict]:
        """
        Try to extract data from Next.js __NEXT_DATA__ script tag.
        
        OfferUp uses Next.js which embeds initial page data in:
          <script id="__NEXT_DATA__" type="application/json">
        
        Args:
            soup: A BeautifulSoup object of the search page.
        
        Returns:
            A list of listing dicts, or empty list.
        """
        script = soup.select_one("script#__NEXT_DATA__")
        if not script:
            return []
        
        try:
            data = json.loads(script.string)
            
            # Navigate through Next.js data structure
            # Try common paths for listing data
            paths = [
                ["props", "pageProps", "items"],
                ["props", "pageProps", "listings"],
                ["props", "pageProps", "results"],
                ["props", "pageProps", "searchResults", "items"],
            ]
            
            for path in paths:
                current = data
                for key in path:
                    if isinstance(current, dict):
                        current = current.get(key, {})
                    else:
                        break
                else:
                    if isinstance(current, list) and len(current) > 0:
                        return current
            
        except (json.JSONDecodeError, TypeError, AttributeError):
            pass
        
        return []
    
    def _parse_item(self, item: dict) -> Optional[ScrapedListing]:
        """
        Convert an OfferUp item dict into a ScrapedListing.
        
        Args:
            item: A listing dict from OfferUp (JSON or API).
        
        Returns:
            A ScrapedListing or None.
        """
        # ── Title ───────────────────────────────────────────────
        title = (
            item.get("title", "") or
            item.get("name", "") or
            item.get("product_name", "") or
            ""
        )
        if not title or "MacBook" not in title:
            return None
        
        # ── Price ───────────────────────────────────────────────
        price = 0
        price_raw = item.get("price", item.get("price_usd", 0))
        if isinstance(price_raw, (int, float)):
            price = float(price_raw)
        elif isinstance(price_raw, str):
            price_text = price_raw.replace("$", "").replace(",", "").strip()
            try:
                price = float(price_text)
            except ValueError:
                return None
        
        if price <= 0:
            return None
        
        # ── URL ─────────────────────────────────────────────────
        listing_id = item.get("id", item.get("item_id", item.get("listing_id", "")))
        url = item.get("url", item.get("link", ""))
        if not url and listing_id:
            url = f"https://offerup.com/item/detail/{listing_id}"
        elif url and not url.startswith("http"):
            url = f"https://offerup.com{url}"
        
        if not url:
            return None
        
        # ── Listing ID ──────────────────────────────────────────
        final_id = self._parse_listing_id(str(listing_id), url)
        
        # ── Condition ───────────────────────────────────────────
        condition = item.get("condition", item.get("item_condition"))
        if not condition:
            # Check description for condition hints
            desc = item.get("description", "") or ""
            if "new" in desc.lower():
                condition = "New"
            elif "used" in desc.lower():
                condition = "Used"
            elif "like new" in desc.lower():
                condition = "Like New"
        
        # ── Parse specs from title ──────────────────────────────
        ram = self.extract_ram(title)
        storage = self.extract_storage(title)
        screen = self.extract_screen(title)
        chip = self.extract_chip(title)
        
        # ── Image URL (optional, not stored but nice to have) ───
        image_url = item.get("image", item.get("image_url", item.get("thumbnail", "")))
        
        return ScrapedListing(
            source=self.source_name,
            listing_id=final_id,
            title=title,
            price_usd=price,
            url=url,
            condition=condition,
            ram_gb=ram,
            storage_gb=storage,
            screen_size=screen,
            chip=chip,
        )
    
    def scrape(self) -> list[ScrapedListing]:
        """
        Scrape OfferUp for MacBook Pro M5 Max listings.
        
        Tries multiple strategies to extract data:
          1. JSON-LD structured data from HTML
          2. Next.js __NEXT_DATA__ embedded state
          3. Internal JSON API
        
        If none work, logs a message about Playwright.
        
        Returns:
            A list of ScrapedListing objects.
        """
        found: list[ScrapedListing] = []
        found_ids: set = set()
        
        for ram in [128, 64]:
            search_url = self._build_search_url(ram)
            
            # ── Strategy 1: Parse HTML for structured data ────
            try:
                html = self.fetch_page(search_url)
                soup = self.parse_html(html)
                
                # Try JSON-LD
                jsonld_items = self._try_jsonld(soup)
                for item in jsonld_items:
                    try:
                        listing = self._parse_item(item)
                        if listing and listing.listing_id not in found_ids:
                            if self.passes_filters(listing):
                                found.append(listing)
                                found_ids.add(listing.listing_id)
                    except Exception:
                        continue
                
                # Try Next.js data (if JSON-LD didn't give enough)
                if not jsonld_items:
                    nextjs_items = self._try_nextjs_data(soup)
                    for item in nextjs_items:
                        try:
                            listing = self._parse_item(item)
                            if listing and listing.listing_id not in found_ids:
                                if self.passes_filters(listing):
                                    found.append(listing)
                                    found_ids.add(listing.listing_id)
                        except Exception:
                            continue
                
            except Exception as e:
                print(f"  [OfferUp] Error fetching/parsing HTML: {e}")
            
            # ── Strategy 2: Try the API directly ──────────────
            if not found:
                try:
                    api_items = self._try_api(ram)
                    for item in api_items:
                        try:
                            listing = self._parse_item(item)
                            if listing and listing.listing_id not in found_ids:
                                if self.passes_filters(listing):
                                    found.append(listing)
                                    found_ids.add(listing.listing_id)
                        except Exception:
                            continue
                except Exception as e:
                    print(f"  [OfferUp] API approach failed: {e}")
        
        # ── Report results ──────────────────────────────────────
        if not found:
            print(
                "  [OfferUp] ⚠️  Could not extract listings — "
                "OfferUp requires JavaScript.  To enable: "
                "pip install playwright && playwright install chromium"
            )
        else:
            print(f"  [OfferUp] Found {len(found)} matching listings")
        
        return found
