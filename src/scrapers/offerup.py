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

from bs4 import BeautifulSoup

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
    
    def _build_fallback_urls(self, url: str) -> list[str]:
        """
        Build the ordered list of search URLs to attempt.

        WHAT: Returns the primary search URL followed by a more
        specific fallback query (product + chip + RAM).

        WHY: OfferUp's generic search sometimes returns a page whose
        embedded data is stripped or empty (anti-bot behavior). A more
        specific query string occasionally dodges that and returns a
        populated page, so we keep it in reserve as a second attempt.

        Args:
            url: The primary OfferUp search URL.

        Returns:
            A list of URLs to try in order.
        """
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

        return urls_to_try

    def _fetch_listings_json(self, url: str) -> list[dict]:
        """
        Load the OfferUp search page and extract listing data.

        WHAT: Drives a headless browser through one or more search
        URLs and, for each page load, tries a chain of extraction
        strategies until one yields listings.

        WHY A FALLBACK CHAIN: OfferUp is a JS-heavy React app whose
        page structure is inconsistent — anti-bot measures, A/B tests,
        and partial renders mean no single extraction approach works
        reliably every time. Trying cheaper/more-structured strategies
        first (embedded JSON) before falling back to messier ones
        (regex over raw HTML) maximizes the chance of getting data
        while keeping the common case fast.

        Strategies tried in order, per page load:
          1. _try_next_data   — Next.js __NEXT_DATA__ embedded JSON
          2. _try_json_ld     — JSON-LD structured data <script> tags
          3. _try_rendered_dom — rendered card elements after extra JS wait
          4. _try_html_links  — regex/CSS scan for /item/detail/ links

        Args:
            url: The OfferUp search URL.

        Returns:
            A list of listing dicts from the search results.
        """
        from playwright.sync_api import sync_playwright

        urls_to_try = self._build_fallback_urls(url)

        last_error = None

        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"],
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

                    listings = self._try_next_data(page)
                    if listings:
                        browser.close()
                        return listings

                    # ── Wait more for JS rendering before DOM-based strategies ──
                    page.wait_for_timeout(8000)
                    html = page.content()
                    soup = BeautifulSoup(html, "lxml")

                    listings = self._try_json_ld(soup)
                    if listings:
                        browser.close()
                        return listings

                    listings = self._try_rendered_dom(soup)
                    if listings:
                        browser.close()
                        return listings

                    listings = self._try_html_links(soup)
                    if listings:
                        browser.close()
                        return listings

                browser.close()

        except Exception as e:
            last_error = e

        if last_error:
            raise Exception(
                f"Playwright error: {last_error}. "
                f"Install: pip install playwright && playwright install chromium"
            ) from last_error

        print("  [OfferUp] No listings found on page")
        return []

    # ── Extraction strategy helpers ───────────────────────────────

    def _try_next_data(self, page) -> list[dict]:
        """
        Strategy 1: extract listings from Next.js __NEXT_DATA__ JSON.

        WHAT: Pulls the text content of the __NEXT_DATA__ <script>
        element via a small JS snippet run in the page context, then
        parses it as JSON.

        WHY THIS APPROACH: __NEXT_DATA__ is the raw server-rendered
        state React hydrates from. It's populated before OfferUp's
        anti-bot logic can strip content, and it's structured JSON
        rather than HTML we'd have to scrape — so it's the fastest
        and most reliable source when present.

        Args:
            page: The Playwright page object, already navigated to the
                  target URL.

        Returns:
            A list of listing dicts, or an empty list if __NEXT_DATA__
            was missing, unparseable, or contained no listings.
        """
        next_data_json = page.evaluate("""
            () => {
                const el = document.getElementById('__NEXT_DATA__');
                return el ? el.textContent : null;
            }
        """)

        if not next_data_json:
            return []

        return self._parse_next_data(next_data_json)

    def _parse_next_data(self, next_data_json: str) -> list[dict]:
        """Parse listings from __NEXT_DATA__ JSON."""
        data = json.loads(next_data_json)
        page_props = data.get("props", {}).get("pageProps", {})
        feed = page_props.get("searchFeedResponse", {})
        loose_tiles = feed.get("looseTiles", [])
        listings = []
        for tile in loose_tiles:
            if tile.get("__typename") == "ModularFeedTileListing":
                listing_data = tile.get("listing", {})
                if listing_data and listing_data.get("title"):
                    listings.append(listing_data)
        return listings

    def _try_json_ld(self, soup: BeautifulSoup) -> list[dict]:
        """
        Strategy 2: extract listings from JSON-LD structured data.

        WHAT: Reads `<script type="application/ld+json">` tags and
        pulls out product-like entries whose name mentions "macbook".

        WHY THIS APPROACH: Many e-commerce pages (including OfferUp's
        rendered search results) embed JSON-LD for SEO purposes. When
        present, it's structured and doesn't depend on CSS class names
        that can change, making it a solid second choice after
        __NEXT_DATA__.

        Args:
            soup: Parsed BeautifulSoup of the rendered page HTML.

        Returns:
            A list of listing dicts, or an empty list if no matching
            JSON-LD entries were found.
        """
        scripts = soup.select("script[type='application/ld+json']")
        listings = []
        for script in scripts:
            try:
                data = json.loads(script.string)
                items = data if isinstance(data, list) else [data]
                for item in items:
                    name = item.get("name", "")
                    if "macbook" not in name.lower():
                        continue
                    url = item.get("url", "")
                    url = self._clean_url(url)
                    id_match = re.search(r'/item/detail/([^/?]+)', url)
                    listing_id = id_match.group(1) if id_match else ""
                    offers = item.get("offers", {})
                    price_str = "0"
                    if isinstance(offers, dict):
                        price_str = offers.get("price", "0")
                    elif isinstance(offers, list) and offers:
                        price_str = offers[0].get("price", "0")
                    listings.append({
                        "listingId": listing_id,
                        "title": name,
                        "price": str(price_str),
                        "conditionText": item.get("condition", ""),
                        "locationName": item.get("areaServed", ""),
                        "url": url,
                    })
            except Exception:
                continue
        return listings
    
    def _try_rendered_dom(self, soup: BeautifulSoup) -> list[dict]:
        """
        Strategy 3: extract listings from rendered DOM card elements.

        WHAT: Scans the fully-JS-rendered page for search-result card
        elements (tried via several CSS selectors, from most to least
        specific) and pulls title/price/condition/location out of each.

        WHY THIS APPROACH: When neither __NEXT_DATA__ nor JSON-LD is
        available, the only remaining source of truth is the rendered
        DOM itself. This is slower and more brittle (depends on class
        names and structure that can change), so it's tried only after
        the more structured strategies fail.

        Args:
            soup: Parsed BeautifulSoup of the rendered page HTML
                  (captured after extra wait time for JS rendering).

        Returns:
            A list of listing dicts, or an empty list if no card
            elements could be parsed into valid listings.
        """
        cards = (
            soup.select("[data-testid='search-card']")
            or soup.select("article")
            or soup.select("div[class*='Card' i]")
            or soup.select("a[href*='/item/detail/']")
        )
        seen_ids = set()
        listings = []
        for card in cards:
            try:
                title = ""
                title_el = card.select_one(
                    "h1, h2, h3, [class*='title' i], [class*='Title'], [aria-label]"
                )
                if title_el:
                    title = title_el.get("aria-label") or title_el.get_text(strip=True) or ""
                if not title:
                    title = card.get("aria-label") or card.get_text(strip=True) or ""
                if not title or "macbook" not in title.lower():
                    continue
                
                price_el = card.select_one(
                    "[class*='price' i], [class*='Price'], [data-testid*='price']"
                )
                price_str = price_el.get_text(strip=True) if price_el else "0"
                price_str = re.sub(r'[$,]', '', price_str)
                price = float(price_str) if price_str else 0
                if price <= 0:
                    continue
                
                link = card if card.name == "a" else card.select_one("a[href*='/item/detail/']")
                url = ""
                if link:
                    url = link.get("href", "")
                    if url and not url.startswith("http"):
                        url = f"https://offerup.com{url}"
                    url = self._clean_url(url)
                
                id_match = re.search(r'/item/detail/([^/?]+)', url)
                listing_id = id_match.group(1) if id_match else ""
                if not listing_id or listing_id in seen_ids:
                    continue
                seen_ids.add(listing_id)
                
                condition_el = card.select_one("[class*='condition' i], [class*='Condition']")
                condition = condition_el.get_text(strip=True) if condition_el else None
                
                location_el = card.select_one("[class*='location' i], [class*='Location']")
                location = location_el.get_text(strip=True) if location_el else None
                
                listings.append({
                    "listingId": listing_id,
                    "title": title,
                    "price": str(price),
                    "conditionText": condition,
                    "locationName": location,
                    "url": url,
                })
            except Exception:
                continue
        return listings
    
    def _try_html_links(self, soup: BeautifulSoup) -> list[dict]:
        """
        Strategy 4: extract listings from raw /item/detail/ links.

        WHAT: Scans all anchor tags linking to `/item/detail/{id}` and
        builds minimal listing dicts from the link and its surrounding
        HTML (title from the link text/aria-label, price from a nearby
        sibling element if present).

        WHY THIS APPROACH: This is the last-resort strategy — it makes
        the fewest assumptions about page structure (just "there's a
        link to an item detail page somewhere") so it's the most
        resilient to layout changes, but it also produces the least
        complete data (e.g. no condition). It's only used when all
        more structured strategies come up empty.

        Args:
            soup: Parsed BeautifulSoup of the rendered page HTML.

        Returns:
            A list of listing dicts, or an empty list if no
            /item/detail/ links were found.
        """
        links = soup.select("a[href*='/item/detail/']")
        seen_ids = set()
        listings = []
        for link in links:
            href = link.get("href", "")
            if not href:
                continue
            if href.startswith("/"):
                href = f"https://offerup.com{href}"
            href = self._clean_url(href)
            
            id_match = re.search(r'/item/detail/([^/?]+)', href)
            if not id_match:
                continue
            listing_id = id_match.group(1)
            if listing_id in seen_ids:
                continue
            seen_ids.add(listing_id)
            
            title = link.get("aria-label", "") or link.get_text(strip=True) or ""
            if "macbook" not in title.lower():
                continue
            
            price = "0"
            parent = link.parent
            if parent:
                price_el = parent.select_one(
                    "[class*='price' i], [class*='Price'], [data-testid*='price']"
                )
                if price_el:
                    price = re.sub(r'[$,]', '', price_el.get_text(strip=True))
            
            listings.append({
                "listingId": listing_id,
                "title": title,
                "price": price,
                "conditionText": None,
                "locationName": None,
                "url": href,
            })
        return listings
    
    @staticmethod
    def _clean_url(url: str) -> str:
        """Strip query parameters and fragments from a URL."""
        url = re.sub(r'\?.*', '', url)
        url = re.sub(r'#.*', '', url)
        return url
    
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
        url = self._clean_url(url)
        
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
        specs = self.parse_common_specs(title)
        ram = specs["ram_gb"]
        storage = specs["storage_gb"]
        screen = specs["screen_size"]
        chip = specs["chip"]
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
            location=location,
            cpu_cores=cpu_cores,
            gpu_cores=gpu_cores,
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
