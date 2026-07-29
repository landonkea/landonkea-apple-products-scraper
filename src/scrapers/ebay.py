# ───────────────────────────────────────────────────────────────────
# eBay scraper
# ───────────────────────────────────────────────────────────────────
# Searches eBay for "Buy It Now" listings matching our MacBook Pro
# specs.  eBay allows searching without an account, making it the
# easiest site to scrape.
# ───────────────────────────────────────────────────────────────────

import re
from typing import Optional

from scrapers.base import BaseScraper, ScrapedListing
from config import Config


class eBayScraper(BaseScraper):
    """
    Scrapes eBay for MacBook Pro M5 Max listings.
    
    eBay search URLs look like:
      https://www.ebay.com/sch/i.html?_nkw=macbook+pro+m5+max+128gb&LH_BIN=1
    
    LH_BIN=1 means "Buy It Only" (no auctions).
    _sop=15 means "sorted by price + shipping: lowest first".
    """
    
    def __init__(self, config: Config):
        """Initialize the eBay scraper."""
        super().__init__(config)
        self.source_name = "ebay"
    
    def _build_search_url(self, ram_gb: int) -> str:
        """
        Build an eBay search URL for a specific RAM configuration.
        
        eBay uses query parameters in the URL:
          _nkw    = the search keywords
          LH_BIN  = 1 means "Buy It Now" only
          _sop    = sort order (15 = price + shipping: lowest first)
          _udhi   = max price (upper bound)
        
        Args:
            ram_gb: RAM in GB (128 or 64).
        
        Returns:
            A fully-formed eBay search URL.
        """
        # Build the search query string
        product = self.config.search.product_name
        chip = self.config.search.chip
        screen = self.config.search.screen_size_inches
        
        query = f"{product} {screen}-inch {chip} {ram_gb}GB"
        
        # URL-encode the query (replace spaces with +)
        encoded_query = query.replace(" ", "+")
        
        # Get the max price threshold
        max_price = int(self.config.price.absolute_max_usd)
        
        # Build the URL
        url = (
            f"https://www.ebay.com/sch/i.html"
            f"?_nkw={encoded_query}"
            # NOTE: LH_ItemCondition includes Auctions (3000)                            
            # so users can bid on great deals too.
            f"&LH_ItemCondition=4|3|2|1500|1000|2000" # Any condition
            f"&_sop=15"                               # Sort: lowest price + shipping
            f"&_udhi={max_price}"                     # Max price filter
            f"&_ipg=120"                              # 120 results per page
        )
        
        return url
    
    def _parse_listing_id(self, url: str) -> str:
        """
        Extract the unique eBay item ID from a listing URL.
        
        eBay URLs look like:
          https://www.ebay.com/itm/123456789012
          https://www.ebay.com/p/1234567890
        
        Args:
            url: The eBay listing URL.
        
        Returns:
            The item ID as a string.
        """
        # eBay item IDs are in the URL as /itm/XXXXXXXXXXX or /p/XXXXXXXXX
        match = re.search(r'/itm/(\d+)', url)
        if match:
            return match.group(1)
        match = re.search(r'/p/(\d+)', url)
        if match:
            return f"p_{match.group(1)}"
        # Fallback: hash the URL
        return f"url_{hash(url)}"
    
    def scrape(self) -> list[ScrapedListing]:
        """
        Scrape eBay for matching MacBook Pro listings.
        
        Searches twice: once for 128GB, once for 64GB.
        Returns all matching listings up to absolute_max_usd.
        
        Returns:
            A list of ScrapedListing objects.
        """
        found: list[ScrapedListing] = []
        
        # Search for both RAM configurations
        for ram in [128, 64]:
            search_url = self._build_search_url(ram)
            
            try:
                html = self.fetch_page(search_url)
                soup = self.parse_html(html)
            except Exception as e:
                print(f"  [eBay] Error fetching search page: {e}")
                continue
            
            # ── Parse search results ────────────────────────────────
            # eBay search results are in <div class="s-item__info">.
            # Each result has a title link and a price.
            
            # Find all listing containers
            items = soup.select("li.s-item")
            
            for item in items:
                try:
                    listing = self._parse_single_item(item)
                    if listing and self.passes_filters(listing):
                        found.append(listing)
                except Exception as e:
                    # Skip any listing that fails to parse
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
        # ── Title and URL ───────────────────────────────────────
        title_elem = item.select_one("a.s-item__link .s-item__title")
        link_elem = item.select_one("a.s-item__link")
        
        if not title_elem or not link_elem:
            return None
        
        title = title_elem.get_text(strip=True)
        url = link_elem.get("href", "")
        
        # Skip the first "Shop on eBay" header item
        if not title or "Shop on eBay" in title:
            return None
        
        # Skip "Contact seller" or classified listings
        if "contact seller" in title.lower():
            return None
        
        # ── Price ───────────────────────────────────────────────
        price_elem = item.select_one(".s-item__price")
        if not price_elem:
            return None
        
        price_text = price_elem.get_text(strip=True)
        # eBay prices look like "$3,999.00" or "From $3,999.00"
        price_match = re.search(r'\$?([0-9,]+(?:\.[0-9]{2})?)', price_text)
        if not price_match:
            return None
        
        price = float(price_match.group(1).replace(",", ""))
        
        # Skip auction-style listings (shouldn't happen with LH_BIN=1,
        # but some listings slip through)
        if "bid" in item.get_text(strict=True).lower():
            return None
        
        # ── Listing ID ──────────────────────────────────────────
        listing_id = self._parse_listing_id(url)
        
        # ── Condition ───────────────────────────────────────────
        condition_elem = item.select_one(".s-item__condition")
        condition = condition_elem.get_text(strip=True) if condition_elem else None
        
        # ── Parse specs from title ──────────────────────────────
        ram = self.extract_ram(title)
        storage = self.extract_storage(title)
        screen = self.extract_screen(title)
        chip = self.extract_chip(title)
        
        # If we can't find RAM in the title, use the search context
        if ram is None:
            # Check if the URL we built was for 128 or 64
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
