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
    
    def _build_search_url(self, screen_size: int) -> str:
        """
        Build an eBay search URL for a specific screen size.
        
        Searches broadly for "MacBook Pro 14-inch" / "MacBook Pro 16-inch"
        sorted by lowest price + shipping first.
        
        Args:
            screen_size: Screen size in inches (14 or 16).
        
        Returns:
            A fully-formed eBay search URL sorted by price ascending.
        """
        product = self.config.search.product_name
        max_price = int(self.config.price.absolute_max_usd)
        
        query = f"{product} {screen_size}-inch"
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
    
    def _fetch_with_playwright(self, url: str) -> str:
        """
        Use Playwright to render an eBay search page.
        
        This bypasses eBay's bot detection that blocks plain requests.
        
        Args:
            url: The eBay search URL.
        
        Returns:
            The page HTML as a string.
        """
        return self.fetch_with_playwright(url)
    
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
        
        for screen_size in self.config.search.screen_sizes:
            search_url = self._build_search_url(screen_size)
            html = None
            
            # Try Playwright first (bypasses bot detection)
            try:
                html = self._fetch_with_playwright(search_url)
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
            items = soup.select("li.s-item")
            if not items:
                items = soup.select("div.s-item")
            if not items:
                items = soup.select("[class*='s-item']")
            if not items:
                items = soup.select("li[data-viewport]")
            if not items:
                items = soup.select("div[data-viewport]")
            
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
        title_elem = item.select_one("a.s-item__link .s-item__title")
        link_elem = item.select_one("a.s-item__link")
        
        if not title_elem or not link_elem:
            return None
        
        title = title_elem.get_text(strip=True)
        url = link_elem.get("href", "")
        
        if not title or "Shop on eBay" in title:
            return None
        
        if "contact seller" in title.lower():
            return None
        
        price_elem = item.select_one(".s-item__price")
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
        
        condition_elem = item.select_one(".s-item__condition")
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
        )
