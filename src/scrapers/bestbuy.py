# ───────────────────────────────────────────────────────────────────
# Best Buy Open Box scraper
# ───────────────────────────────────────────────────────────────────
# Best Buy sells "Open Box" items — products that were returned
# by customers but are still in good condition.  They come with
# the same warranty as new but at a significant discount.
#
# Best Buy search pages are server-rendered (not JavaScript).
# This means we CAN scrape them with requests + BeautifulSoup.
#
# Open Box condition grades (best to worst):
#   - Open Box - Excellent   (like new, full accessories)
#   - Open Box - Certified   (minor wear, all accessories)
#   - Open Box - Satisfactory (noticeable wear, may miss accessories)
#
# NOTE: Best Buy has mild bot detection.  If we get blocked,
# we may need to add proxy support later.
# ───────────────────────────────────────────────────────────────────

import re
from typing import Optional

from scrapers.base import BaseScraper, ScrapedListing
from config import Config


class BestBuyScraper(BaseScraper):
    """
    Scrapes Best Buy for Open Box MacBook Pro M5 Max listings.
    
    Searches for MacBook Pro M5 Max and filters results to only
    include items marked as "Open Box" condition.
    
    Best Buy search URLs look like:
      https://www.bestbuy.com/site/searchpage.jsp?st=macbook+pro+m5+max
    """
    
    def __init__(self, config: Config):
        """Initialize the Best Buy scraper."""
        super().__init__(config)
        self.source_name = "bestbuy"
    
    def _build_search_url(self, ram_gb: int) -> str:
        """
        Build a Best Buy search URL for a specific RAM config.
        
        Best Buy uses query parameters:
          st  = search terms
          cp  = page number (1)
          iht = inventory filter (y = in stock only)
        
        We add an "af" parameter to filter for Open Box items:
          af=condition%3Aopen+box
        
        Args:
            ram_gb: RAM in GB (128 or 64).
        
        Returns:
            A fully-formed Best Buy search URL.
        """
        product = self.config.search.product_name
        chip = self.config.search.chip
        screen = self.config.search.screen_size_inches
        
        # Build the search query
        query = f"{product} {screen}-inch {chip} {ram_gb}GB"
        encoded_query = query.replace(" ", "+")
        
        # Max price filter
        max_price = int(self.config.price.absolute_max_usd)
        
        url = (
            f"https://www.bestbuy.com/site/searchpage.jsp"
            f"?st={encoded_query}"
            f"&cp=1"                                              # Page 1
            f"&iht=y"                                            # In stock only
            f"&af=condition%3Aopen+box"                           # Open Box filter
            f"&_dyncharset=UTF-8"
            f"&id=pcat17071"
            f"&type=page"
            f"&sc=Global"
            f"&nrp="
            f"&sp="
            f"&qp="
            f"&list=n"
            f"&fs=sa"
            f"&sa=1"
        )
        
        return url
    
    def _parse_listing_id(self, url: str) -> str:
        """
        Extract the Best Buy SKU from a listing URL.
        
        Best Buy URLs look like:
          https://www.bestbuy.com/site/macbook-pro/1234567.p
          https://www.bestbuy.com/site/macbook-pro/1234567
        
        Args:
            url: The Best Buy listing URL.
        
        Returns:
            The SKU as a string.
        """
        # Best Buy SKUs are in the URL path as /XXXXXXX.p or /XXXXXXX
        match = re.search(r'/(\d{6,})\.p', url)
        if match:
            return match.group(1)
        match = re.search(r'/(\d{6,})(?:\?|$)', url)
        if match:
            return match.group(1)
        # Fallback: hash the URL
        return f"url_{hash(url)}"
    
    def scrape(self) -> list[ScrapedListing]:
        """
        Scrape Best Buy for Open Box MacBook Pro M5 Max listings.
        
        Searches for both 128GB and 64GB configurations.
        Only returns items marked as "Open Box" condition.
        
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
                print(f"  [Best Buy] Error fetching search page: {e}")
                continue
            
            # ── Parse search results ────────────────────────────────
            # Best Buy uses <li class="sku-item"> for each product.
            
            # Try multiple selectors Best Buy might use
            items = soup.select("li.sku-item")
            if not items:
                items = soup.select("div.sku-item")
            if not items:
                items = soup.select("[class*='sku-item']")
            
            for item in items:
                try:
                    listing = self._parse_single_item(item)
                    if listing and self.passes_filters(listing):
                        found.append(listing)
                except Exception:
                    continue
        
        print(f"  [Best Buy] Found {len(found)} matching Open Box listings")
        return found
    
    def _get_condition(self, item) -> Optional[str]:
        """
        Extract the condition label from a Best Buy listing.
        
        Best Buy shows condition as a badge or text label.
        Open Box items have labels like:
          - "Open Box - Excellent"
          - "Open Box - Certified"
          - "Open Box - Satisfactory"
        
        Args:
            item: A BeautifulSoup tag for one listing.
        
        Returns:
            The condition string, or None if not found.
        """
        # Look for condition badges in various selectors
        condition_texts = []
        
        # Try multiple places where condition might appear
        selectors = [
            ".open-box-condition",
            ".condition-badge",
            ".condition-label",
            "[data-condition]",
            ".sku-condition",
            ".badge",
            ".product-condition",
        ]
        
        for selector in selectors:
            elem = item.select_one(selector)
            if elem:
                text = elem.get_text(strip=True)
                if text and "open box" in text.lower():
                    condition_texts.append(text)
        
        # Look for "Open Box" anywhere in the item text
        full_text = item.get_text(" ", strip=True)
        ob_match = re.search(
            r'(Open\s*Box\s*[-–—]?\s*\w+)', full_text, re.IGNORECASE
        )
        if ob_match:
            return ob_match.group(1).strip()
        
        # If we found condition text, return it
        if condition_texts:
            return condition_texts[0]
        
        # Check if this is an Open Box item by looking for
        # "Open Box" text in the item
        if "Open Box" in full_text or "open-box" in full_text:
            return "Open Box"
        
        return None
    
    def _parse_single_item(self, item) -> Optional[ScrapedListing]:
        """
        Parse a single Best Buy search result item.
        
        Args:
            item: A BeautifulSoup tag for one Best Buy listing.
        
        Returns:
            A ScrapedListing or None if parsing fails.
        """
        # ── Condition ──────────────────────────────────────────────
        # Only include Open Box items
        condition = self._get_condition(item)
        if not condition:
            return None
        if "open box" not in condition.lower():
            return None
        
        # ── Title and URL ───────────────────────────────────────
        # Best Buy uses <h4 class="sku-header"> with a link inside
        title_elem = item.select_one("h4.sku-header a, .sku-header a, h4 a")
        if not title_elem:
            title_elem = item.select_one("a[class*='title'], a[href*='/site/']")
        if not title_elem:
            return None
        
        title = title_elem.get_text(strip=True)
        url = title_elem.get("href", "")
        
        if not title or "MacBook" not in title:
            return None
        
        # Make URL absolute
        if url and url.startswith("/"):
            url = "https://www.bestbuy.com" + url
        
        # ── Price ───────────────────────────────────────────────
        # Best Buy prices are in <div class="priceView-hero-price">
        price_elem = item.select_one(
            ".priceView-hero-price span, "
            ".price-view-hero-price span, "
            "[class*='priceView'] span, "
            ".price"
        )
        if not price_elem:
            return None
        
        price_text = price_elem.get_text(strip=True)
        # Prices look like "$3,999.99"
        price_text = price_text.replace("$", "").replace(",", "")
        price_match = re.search(r'(\d+(?:\.\d{2})?)', price_text)
        if not price_match:
            return None
        price = float(price_match.group(1))
        
        # ── Listing ID ──────────────────────────────────────────
        listing_id = self._parse_listing_id(url)
        
        # ── Parse specs from title ──────────────────────────────
        ram = self.extract_ram(title)
        storage = self.extract_storage(title)
        screen = self.extract_screen(title)
        chip = self.extract_chip(title)
        
        # If no RAM found in title, infer from search context
        if ram is None:
            if "128GB" in url:
                ram = 128
            elif "64GB" in url:
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
