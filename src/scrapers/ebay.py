# ───────────────────────────────────────────────────────────────────
# eBay scraper
# ───────────────────────────────────────────────────────────────────
# Searches eBay for "Buy It Now" listings matching our MacBook Pro
# specs.  eBay allows searching without an account, making it the
# easiest site to scrape.
# ───────────────────────────────────────────────────────────────────

import json
import re
import time
from typing import Optional

from scrapers.base import BaseScraper, ScrapedListing
from config import Config


class eBayScraper(BaseScraper):
    """
    Scrapes eBay for MacBook Pro M5 Max listings.
    
    Uses Playwright to render the page (bypasses eBay's bot detection).
    Falls back to plain requests if Playwright fails.
    """
    
    def __init__(self, config: Config):
        """Initialize the eBay scraper."""
        super().__init__(config)
        self.source_name = "ebay"
    
    def _build_search_url(self, screen_size: Optional[int]) -> str:
        """
        Build an eBay search URL for a specific screen size.
        
        Searches broadly for "MacBook Pro 14-inch" / "MacBook Pro 16-inch"
        sorted by lowest price + shipping first.
        
        Args:
            screen_size: Screen size in inches (14 or 16), or None for products without screen sizes.
        
        Returns:
            A fully-formed eBay search URL sorted by price ascending.
        """
        product = self.config.search.product_name
        max_price = int(self.config.price.absolute_max_usd)
        
        if screen_size:
            query = f"{product} {screen_size}-inch"
        else:
            query = product
        encoded_query = query.replace(" ", "+")
        
        url = (
            f"https://www.ebay.com/sch/i.html"
            f"?_nkw={encoded_query}"
            f"&LH_ItemCondition=4|3|2|1500|1000|2000"
            f"&_sop=15"
            f"&_udhi={max_price}"
            f"&_ipg=120"
        )
        
        return url
    
    def _parse_listing_id(self, url: str) -> str:
        """Extract the unique eBay item ID from a listing URL."""
        match = re.search(r'/itm/(\d+)', url)
        if match:
            return match.group(1)
        match = re.search(r'/p/(\d+)', url)
        if match:
            return f"p_{match.group(1)}"
        return f"url_{hash(url)}"
    
    def _fetch_listings_json(self, search_url: str) -> str:
        """
        Fetch eBay search results using Playwright.
        
        Warms up with the homepage first (sets cookies, passes bot
        check) in the SAME browser session, then navigates to the
        actual search URL.  Cookies carry over because we keep the
        browser open.
        
        Args:
            search_url: The eBay search URL to scrape.
        
        Returns:
            The search page HTML as a string.
        """
        try:
            from playwright.sync_api import sync_playwright
            
            with sync_playwright() as playwright:
                # Launch a headless Chromium browser
                browser = playwright.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox"],
                )
                
                # Create a real-looking browser context
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US",
                )
                page = context.new_page()
                
                # Step 1: Warm up with the homepage
                # This sets eBay session cookies and proves we are
                # a real browser, not a bot.
                page.goto("https://www.ebay.com", wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)
                
                # Step 2: Navigate to the actual search URL
                # The session cookies from step 1 carry over.
                page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)
                
                # Get the page HTML
                html = page.content()
                browser.close()
                return html
                
        except Exception as e:
            raise Exception(f"Playwright failed: {e}") from e
    
    def scrape(self) -> list[ScrapedListing]:
        """
        Scrape eBay for MacBook Pro listings sorted by price ascending.
        
        Iterates over configured screen sizes, takes top N cheapest
        per size.
        
        Returns:
            A list of ScrapedListing objects.
        """
        found: list[ScrapedListing] = []
        found_ids: set = set()
        
        screen_sizes = self.config.search.screen_sizes
        sizes_to_search = screen_sizes if screen_sizes else [None]
        
        for screen_size in sizes_to_search:
            search_url = self._build_search_url(screen_size)
            html = None
            
            # Try Playwright first (bypasses bot detection)
            try:
                html = self._fetch_listings_json(search_url)
            except Exception as e:
                print(f"  [eBay] Playwright failed: {e}, trying plain request...")
                try:
                    html = self.fetch_page(search_url)
                except Exception as e2:
                    print(f"  [eBay] Plain request also failed: {e2}")
                    continue
            
            if not html:
                continue
            
            soup = self.parse_html(html)
            
            # Try Playwright-rendered selectors first
            items = soup.select("li.s-card")
            if not items:
                items = soup.select("div.s-card")
            if not items:
                items = soup.select("[class*='s-card']")
            if not items:
                items = soup.select("li[data-viewport]")
            if not items:
                items = soup.select("div[data-viewport]")
            # Fallback: server-rendered eBay HTML (plain request)
            if not items:
                items = soup.select("li.s-item")
            if not items:
                items = soup.select(".s-item__wrapper")
            if not items:
                items = soup.select("[data-view*='grid'] li")
            if not items:
                items = soup.select("[id*='srp-river'] li")
            if not items:
                items = soup.select("ul.srp-results li")
            
            results_for_size = 0
            max_results = self.config.search.results_per_size
            
            for item in items:
                if results_for_size >= max_results:
                    break
                try:
                    listing = self._parse_single_item(item)
                    if listing and listing.listing_id not in found_ids:
                        if self.passes_filters(listing):
                            found.append(listing)
                            found_ids.add(listing.listing_id)
                            results_for_size += 1
                except Exception:
                    continue
        
        print(f"  [eBay] Found {len(found)} matching listings")
        return found
    
    def _parse_single_item(self, item) -> Optional[ScrapedListing]:
        """
        Parse a single eBay search result item.
        
        Args:
            item: A BeautifulSoup tag for one eBay listing.
        
        Returns:
            A ScrapedListing or None if parsing fails.
        """
        # Try Playwright-rendered selectors first
        title_elem = item.select_one(".s-card__title")
        link_elem = item.select_one(".su-card-container__header a.s-card__link")
        price_elem = item.select_one(".s-card__price")
        condition_elem = item.select_one(".s-card__subtitle")
        
        # Fallback: server-rendered selectors
        if not title_elem or not link_elem:
            title_elem = item.select_one(".s-item__title")
            link_elem = item.select_one("a.s-item__link")
            price_elem = item.select_one(".s-item__price")
            condition_elem = item.select_one(".s-item__subtitle")
        
        if not title_elem or not link_elem:
            return None
        
        title = title_elem.get_text(strip=True)
        url = link_elem.get("href", "")
        
        if not title or "Shop on eBay" in title:
            return None
        
        if "contact seller" in title.lower():
            return None
        
        if not price_elem:
            return None
        
        price_text = price_elem.get_text(strip=True)
        price_match = re.search(r'\$?([0-9,]+(?:\.[0-9]{2})?)', price_text)
        if not price_match:
            return None
        
        price = float(price_match.group(1).replace(",", ""))
        
        if "bid" in item.get_text(strip=True).lower():
            return None
        
        listing_id = self._parse_listing_id(url)
        
        condition = condition_elem.get_text(strip=True) if condition_elem else None
        
        ram = self.extract_ram(title)
        storage = self.extract_storage(title)
        screen = self.extract_screen(title)
        chip = self.extract_chip(title)
        
        if ram is None:
            if "128GB" in url or "128+GB" in url:
                ram = 128
            elif "64GB" in url or "64+GB" in url:
                ram = 64
        
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
        )
