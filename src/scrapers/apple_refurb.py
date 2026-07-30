# ───────────────────────────────────────────────────────────────────
# Apple Certified Refurbished scraper
# ───────────────────────────────────────────────────────────────────
# Scrapes Apple's official refurbished store. Apple lists all
# refurbished Macs on a single page with product cards.
# ───────────────────────────────────────────────────────────────────

from typing import Optional
from scrapers.base import BaseScraper, ScrapedListing
from config import Config


class AppleRefurbScraper(BaseScraper):
    """
    Scrapes Apple's Certified Refurbished MacBook Pro listings.
    
    Apple's refurb page is a beautiful, clean HTML page — easy to
    parse.  Each product is in a <div class="product-card">.
    """
    
    def __init__(self, config: Config):
        """Initialize the Apple Refurb scraper."""
        super().__init__(config)
        self.source_name = "apple_refurb"
    
    def scrape(self) -> list[ScrapedListing]:
        """
        Scrape Apple's refurbished store for matching MacBook Pros.
        
        Returns:
            A list of ScrapedListing objects.
        """
        found: list[ScrapedListing] = []
        
        # Get the refurbished Mac page
        url = "https://www.apple.com/shop/refurbished/mac/2026-macbook-pro"
        
        # Also check generic MacBook Pro refurb page for older models
        alt_url = "https://www.apple.com/shop/refurbished/mac/macbook-pro"
        
        for page_url in [url, alt_url]:
            try:
                html = self.fetch_page(page_url)
                soup = self.parse_html(html)
                
                # Apple uses product-card class for each item
                # Try multiple selectors Apple might use
                cards = soup.select("div.product-card")
                if not cards:
                    cards = soup.select("div.rc-productcard")
                if not cards:
                    cards = soup.select("[data-product-card]")
                
                for card in cards:
                    try:
                        listing = self._parse_card(card)
                        if listing and self.passes_filters(listing):
                            found.append(listing)
                    except Exception:
                        continue
                        
            except Exception as e:
                print(f"  [Apple Refurb] Error fetching {page_url}: {e}")
                continue
        
        print(f"  [Apple Refurb] Found {len(found)} matching listings")
        return found
    
    def _parse_card(self, card) -> Optional[ScrapedListing]:
        """
        Parse a single product card from Apple's refurb page.
        
        Args:
            card: A BeautifulSoup tag for one product card.
        
        Returns:
            A ScrapedListing or None if it doesn't match.
        """
        # ── Title ───────────────────────────────────────────────
        # Apple's titles look like:
        # "Refurbished 14-inch MacBook Pro Apple M5 Max chip with
        #  18‑Core CPU and 40‑Core GPU - Space Black"
        title_elem = card.select_one("h3, .product-card-title, .title")
        if not title_elem:
            return None
        
        title = title_elem.get_text(strip=True)
        if not title or "MacBook Pro" not in title:
            return None
        
        # ── Price ───────────────────────────────────────────────
        price_elem = card.select_one(
            ".product-card-price, .price, [data-product-price]"
        )
        if not price_elem:
            return None
        
        price_text = price_elem.get_text(strip=True)
        # Apple prices look like "$6,669.00"
        price_text = price_text.replace("$", "").replace(",", "")
        try:
            price = float(price_text)
        except ValueError:
            return None
        
        # ── URL ─────────────────────────────────────────────────
        link_elem = card.select_one("a")
        url = ""
        if link_elem:
            url = link_elem.get("href", "")
            if url and not url.startswith("http"):
                url = "https://www.apple.com" + url
        
        # ── Parse specs ─────────────────────────────────────────
        ram = self.extract_ram(title)
        storage = self.extract_storage(title)
        screen = self.extract_screen(title)
        chip = self.extract_chip(title)
        
        # Apple refurb pages always have 14" MacBook Pro in the title.
        # If we couldn't detect screen size from title, assume 14"
        # since that's the only 14" product on this page.
        if screen is None and "14" in title:
            screen = 14.0
        
        # ── Listing ID ──────────────────────────────────────────
        # Use the URL path as the ID since Apple doesn't have
        # traditional listing IDs.
        listing_id = f"apple_{hash(title)}"
        
        return ScrapedListing(
            source=self.source_name,
            listing_id=listing_id,
            title=title,
            price_usd=price,
            url=url,
            condition="Certified Refurbished",
            ram_gb=ram,
            storage_gb=storage,
            screen_size=screen,
            chip=chip,
            location=None,
        )
