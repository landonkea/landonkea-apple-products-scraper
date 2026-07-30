# ───────────────────────────────────────────────────────────────────
# Swappa scraper
# ───────────────────────────────────────────────────────────────────
# Swappa is a marketplace for used/refurbished devices.
# They have a public API that returns JSON — much easier than
# scraping HTML.  No login required for browsing.
# ───────────────────────────────────────────────────────────────────

import re
from typing import Optional

from scrapers.base import BaseScraper, ScrapedListing
from config import Config


class SwappaScraper(BaseScraper):
    """
    Scrapes Swappa for MacBook Pro M5 Max listings.
    
    Swappa has a JSON API endpoint:
      https://swappa.com/api/macbook-pro/m5-max/listings
    
    This returns structured data we can parse directly.
    """
    
    def __init__(self, config: Config):
        """Initialize the Swappa scraper."""
        super().__init__(config)
        self.source_name = "swappa"
        
        # Swappa uses an API key even for public endpoints.
        # We send a reasonable User-Agent instead.
        # If Swappa blocks us, we'll need a real API key.
        self.api_base = "https://swappa.com/api"
    
    def _fetch_listings_json(self) -> list[dict]:
        """
        Fetch listings from Swappa's API.
        
        Swappa organizes devices by type, then chip, then generation.
        For M5 Max MacBook Pro:
          /api/macbook-pro/m5-max/listings
        
        Returns:
            A list of listing dicts from the API.
        """
        listings = []
        
        # Build the API URL for M5 Max MacBook Pro listings
        api_url = f"{self.api_base}/macbook-pro/m5-max/listings"
        
        try:
            # Fetch JSON directly (not HTML)
            import time
            time.sleep(1.0)
            
            response = self.session.get(api_url, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                # Swappa API returns listings in a "listings" key
                listings = data.get("listings", data.get("results", []))
            
        except Exception as e:
            print(f"  [Swappa] Error: {e}")
            
            # Fallback: try HTML scraping if API fails
            try:
                listings = self._scrape_html_fallback()
            except Exception:
                pass
        
        return listings
    
    def _scrape_html_fallback(self) -> list[dict]:
        """
        Fallback method: scrape Swappa's HTML search page.
        
        Used if the JSON API returns an error.
        
        Returns:
            A list of listing dicts (simulated from HTML).
        """
        fallback_listings = []
        
        # Search for M5 Max MacBook Pro on Swappa
        search_url = (
            "https://swappa.com/search?q=macbook+pro+m5+max+14+inch"
        )
        
        html = self.fetch_page(search_url)
        soup = self.parse_html(html)
        
        # Swappa listing cards use a specific class structure
        cards = soup.select("div.listing-card, div[data-listing]")
        
        for card in cards:
            try:
                listing_data = self._parse_html_card(card)
                if listing_data:
                    fallback_listings.append(listing_data)
            except Exception:
                continue
        
        return fallback_listings
    
    def _parse_html_card(self, card) -> Optional[dict]:
        """
        Parse a Swappa listing card from HTML.
        
        Args:
            card: A BeautifulSoup tag for one listing.
        
        Returns:
            A dict with listing data, or None.
        """
        # Title
        title_elem = card.select_one("h3, .listing-title")
        if not title_elem:
            return None
        title = title_elem.get_text(strip=True)
        
        # Price
        price_elem = card.select_one(".price, .listing-price")
        if not price_elem:
            return None
        price_text = price_elem.get_text(strip=True).replace("$", "").replace(",", "")
        try:
            price = float(price_text)
        except ValueError:
            return None
        
        # URL
        link = card.select_one("a")
        url = link.get("href", "") if link else ""
        if url and not url.startswith("http"):
            url = f"https://swappa.com{url}"
        
        # Condition is usually shown as a badge
        condition_elem = card.select_one(".condition, .badge")
        condition = condition_elem.get_text(strip=True) if condition_elem else None
        
        return {
            "title": title,
            "price": price,
            "url": url,
            "condition": condition,
        }
    
    def _parse_item(self, item: dict) -> Optional[ScrapedListing]:
        """
        Convert a Swappa API listing dict into a ScrapedListing.
        
        Args:
            item: A listing dict from the Swappa API.
        
        Returns:
            A ScrapedListing or None.
        """
        # ── Title ───────────────────────────────────────────────
        title = item.get("title", "") or item.get("name", "")
        if not title:
            return None
        
        # ── Price ───────────────────────────────────────────────
        price = item.get("price", 0)
        if isinstance(price, str):
            price = float(price.replace("$", "").replace(",", ""))
        
        # ── URL ─────────────────────────────────────────────────
        # Swappa URLs look like https://swappa.com/listing/XXXXX
        listing_path = item.get("url", item.get("slug", ""))
        if listing_path and not listing_path.startswith("http"):
            url = f"https://swappa.com{listing_path}"
        else:
            url = listing_path or ""
        
        # ── Listing ID ──────────────────────────────────────────
        listing_id = str(item.get("id", item.get("listing_id", hash(title))))
        
        # ── Condition ───────────────────────────────────────────
        condition = item.get("condition", item.get("item_condition"))
        
        # ── Parse specs from title ──────────────────────────────
        ram = self.extract_ram(title)
        storage = self.extract_storage(title)
        screen = self.extract_screen(title)
        chip = self.extract_chip(title)
        
        return ScrapedListing(
            source=self.source_name,
            listing_id=listing_id,
            title=title,
            price_usd=float(price),
            url=url,
            condition=condition,
            ram_gb=ram,
            storage_gb=storage,
            screen_size=screen,
            chip=chip,
        )
    
    def scrape(self) -> list[ScrapedListing]:
        """
        Scrape Swappa for MacBook Pro listings sorted by price.
        
        Returns:
            A list of ScrapedListing objects.
        """
        found: list[ScrapedListing] = []
        found_ids: set = set()
        
        # Try the JSON API first
        try:
            listings_data = self._fetch_listings_json()
            
            for item in listings_data:
                try:
                    listing = self._parse_item(item)
                    if listing and listing.listing_id not in found_ids:
                        if self.passes_filters(listing):
                            found.append(listing)
                            found_ids.add(listing.listing_id)
                except Exception:
                    continue
        except Exception as e:
            print(f"  [Swappa] Error parsing listings: {e}")
        
        print(f"  [Swappa] Found {len(found)} matching listings")
        return found
