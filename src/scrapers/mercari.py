# ───────────────────────────────────────────────────────────────────
# Mercari scraper
# ───────────────────────────────────────────────────────────────────
# Mercari is a peer-to-peer marketplace (like eBay but simpler).
# No login required for browsing.  Good for used MacBook Pros.
# ───────────────────────────────────────────────────────────────────

import re
from typing import Optional
from urllib.parse import quote

from scrapers.base import BaseScraper, ScrapedListing
from config import Config


class MercariScraper(BaseScraper):
    """
    Scrapes Mercari for MacBook Pro M5 Max listings.
    
    Mercari's search page returns clean HTML with product cards.
    We search for both 128GB and 64GB configurations.
    """
    
    def __init__(self, config: Config):
        """Initialize the Mercari scraper."""
        super().__init__(config)
        self.source_name = "mercari"
    
    def _build_search_url(self, ram_gb: int) -> str:
        """
        Build a Mercari search URL for the given RAM config.
        
        Mercari uses keyword-based search:
          https://www.mercari.com/search/?keyword=macbook+pro+m5+max+128gb
        
        Args:
            ram_gb: RAM in GB.
        
        Returns:
            A Mercari search URL.
        """
        product = self.config.search.product_name
        chip = self.config.search.chip
        screen = self.config.search.screen_size_inches
        
        query = f"{product} {screen}inch {chip} {ram_gb}gb"
        encoded = quote(query)
        
        return f"https://www.mercari.com/search/?keyword={encoded}"
    
    def scrape(self) -> list[ScrapedListing]:
        """
        Scrape Mercari for matching listings.
        
        Returns:
            A list of ScrapedListing objects.
        """
        found: list[ScrapedListing] = []
        
        for ram in [128, 64]:
            url = self._build_search_url(ram)
            
            try:
                html = self.fetch_page(url)
                soup = self.parse_html(html)
                
                # Mercari uses item cards with specific data attributes
                cards = soup.select("[data-testid='item-card'], .item-card")
                if not cards:
                    cards = soup.select("li[class*='item']")
                if not cards:
                    cards = soup.select("a[href*='/items/']")
                    # If we got links, wrap them in parent containers
                    cards = [link.parent for link in cards if link.parent]
                
                for card in cards:
                    try:
                        listing = self._parse_card(card)
                        if listing and self.passes_filters(listing):
                            found.append(listing)
                    except Exception:
                        continue
                        
            except Exception as e:
                print(f"  [Mercari] Error fetching page: {e}")
                continue
        
        print(f"  [Mercari] Found {len(found)} matching listings")
        return found
    
    def _parse_card(self, card) -> Optional[ScrapedListing]:
        """
        Parse a single Mercari item card.
        
        Args:
            card: A BeautifulSoup tag for one item.
        
        Returns:
            A ScrapedListing or None.
        """
        # ── Title ───────────────────────────────────────────────
        # Mercari titles are in <span> or <h3> inside the card
        title_elem = card.select_one(
            "h3, span[class*='title'], [data-testid='item-name']"
        )
        if not title_elem:
            return None
        
        title = title_elem.get_text(strip=True)
        if not title or "MacBook" not in title:
            return None
        
        # ── Price ───────────────────────────────────────────────
        price_elem = card.select_one(
            "span[class*='price'], [data-testid='item-price']"
        )
        if not price_elem:
            return None
        
        price_text = price_elem.get_text(strip=True)
        price_text = price_text.replace("$", "").replace(",", "")
        price_match = re.search(r'(\d+(?:\.\d{2})?)', price_text)
        if not price_match:
            return None
        price = float(price_match.group(1))
        
        # ── URL ─────────────────────────────────────────────────
        link_elem = card.select_one("a")
        url = ""
        if link_elem:
            url = link_elem.get("href", "")
            if url and not url.startswith("http"):
                url = f"https://www.mercari.com{url}"
        
        # ── Listing ID ──────────────────────────────────────────
        # Mercari IDs are in the URL path: /items/m1234567890
        listing_id = f"mercari_{hash(url)}"
        
        # ── Condition ───────────────────────────────────────────
        # Mercari typically doesn't show condition in search results
        condition = None
        
        # ── Parse specs ─────────────────────────────────────────
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
        )
