# ───────────────────────────────────────────────────────────────────
# Back Market scraper
# ───────────────────────────────────────────────────────────────────
# Back Market is a marketplace for refurbished electronics.
# They list MacBooks with condition grades (Fair, Good, Excellent,
# Certified) and prices.
# ───────────────────────────────────────────────────────────────────

import re
from typing import Optional

from scrapers.base import BaseScraper, ScrapedListing
from config import Config


class BackMarketScraper(BaseScraper):
    """
    Scrapes Back Market for refurbished MacBook Pro M5 Max listings.
    
    Back Market's search page is JavaScript-heavy, so we target
    their search endpoint which returns product cards with pricing.
    """
    
    def __init__(self, config: Config):
        """Initialize the Back Market scraper."""
        super().__init__(config)
        self.source_name = "backmarket"
    
    def _build_search_url(self, ram_gb: int) -> str:
        """
        Build a Back Market search URL.
        
        Args:
            ram_gb: RAM in GB (128 or 64).
        
        Returns:
            A Back Market search URL.
        """
        product = self.config.search.product_name
        chip = self.config.search.chip
        screen = self.config.search.screen_size_inches
        
        query = f"{product} {screen}-inch {chip} {ram_gb}GB"
        encoded = query.replace(" ", "+")
        
        return f"https://www.backmarket.com/search?q={encoded}"
    
    def scrape(self) -> list[ScrapedListing]:
        """
        Scrape Back Market for matching MacBook Pro listings.
        
        Returns:
            A list of ScrapedListing objects.
        """
        found: list[ScrapedListing] = []
        
        for ram in [128, 64]:
            url = self._build_search_url(ram)
            
            try:
                html = self.fetch_page(url)
                soup = self.parse_html(html)
                
                # Back Market uses article cards for products.
                # Try multiple selectors as the site may vary.
                cards = soup.select("article[data-qa]")
                if not cards:
                    cards = soup.select("div.cell-productCard")
                if not cards:
                    cards = soup.select("[data-test='product-card']")
                
                for card in cards:
                    try:
                        listing = self._parse_card(card)
                        if listing and self.passes_filters(listing):
                            found.append(listing)
                    except Exception:
                        continue
                        
            except Exception as e:
                print(f"  [Back Market] Error fetching page: {e}")
                continue
        
        print(f"  [Back Market] Found {len(found)} matching listings")
        return found
    
    def _parse_card(self, card) -> Optional[ScrapedListing]:
        """
        Parse a single product card from Back Market.
        
        Args:
            card: A BeautifulSoup tag for one product.
        
        Returns:
            A ScrapedListing or None.
        """
        # ── Title ───────────────────────────────────────────────
        title_elem = card.select_one("h3, h2, .product-title")
        if not title_elem:
            return None
        
        title = title_elem.get_text(strip=True)
        if not title or "MacBook Pro" not in title:
            return None
        
        # ── Price ───────────────────────────────────────────────
        price_elem = card.select_one(
            ".price, .product-price, [data-test='price']"
        )
        if not price_elem:
            return None
        
        price_text = price_elem.get_text(strip=True)
        price_text = price_text.replace("$", "").replace(",", "").replace(" ", "")
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
                url = f"https://www.backmarket.com{url}"
        
        # ── Condition ───────────────────────────────────────────
        condition_elem = card.select_one(
            ".condition, .grade, [data-test='condition']"
        )
        condition = condition_elem.get_text(strip=True) if condition_elem else None
        
        # ── Listing ID ──────────────────────────────────────────
        listing_id = f"bm_{hash(title)}"
        
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
            condition=condition or "Refurbished",
            ram_gb=ram,
            storage_gb=storage,
            screen_size=screen,
            chip=chip,
        )
