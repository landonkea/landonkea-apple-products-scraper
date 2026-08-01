# ───────────────────────────────────────────────────────────────────
# Base scraper class — every marketplace scraper inherits from this
# ───────────────────────────────────────────────────────────────────
# This is the "template" for all scrapers.  It defines:
#   1. The structure every scraper must follow (the interface)
#   2. Shared helper methods (HTTP fetching, spec parsing)
#
# To add a new marketplace, create a file in scrapers/ that
# inherits from BaseScraper and implements scrape().
# ───────────────────────────────────────────────────────────────────

import random
import time
from abc import ABC, abstractmethod
from typing import Optional
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

from config import Config
from product_types import PRODUCT_TYPES

# Re-exported for backward compatibility — this logic moved to
# src/product_types/electronics.py (the electronics ProductTypeHandler)
# so it's no longer hardcoded into every scraper's base class, but
# existing direct imports (e.g. tests/test_scrapers.py) keep working
# unchanged. See src/product_types/base.py for why this moved and how
# to add a new product type.
from product_types.electronics import (  # noqa: F401
    extract_ram_gb,
    extract_storage_gb,
    extract_screen_size,
    extract_chip,
    extract_core_counts,
    is_likely_macbook_pro,
    is_likely_iphone,
    ACCESSORY_KEYWORDS,
    IPHONE_ACCESSORY_KEYWORDS,
    IPHONE_BAD_KEYWORDS,
    MINIMUM_PRICE_USD,
    MINIMUM_IPHONE_PRICE_USD,
)


# ── Data class for a parsed listing ────────────────────────────────
# This is the standard format every scraper returns.
# The main.py orchestrator converts these into database rows.
@dataclass
class ScrapedListing:
    """
    One listing found on a marketplace.
    
    Every scraper returns a list of these.
    """
    source: str                # e.g. "ebay", "swappa"
    listing_id: str            # The marketplace's ID for this item
    title: str                 # Full listing title
    price_usd: float           # Price in dollars
    url: str                   # Direct link to the listing
    condition: Optional[str]   # "New", "Used", "Certified Refurbished", etc.
    ram_gb: Optional[int]      # Parsed from title (e.g. 128, 64)
    storage_gb: Optional[int]  # Parsed from title (e.g. 2048, 4096)
    screen_size: Optional[float]  # Parsed from title (e.g. 14.0)
    chip: Optional[str]        # Parsed from title (e.g. "M5 Max")
    location: Optional[str]    # City/state from the listing
    cpu_cores: Optional[int] = None  # Parsed from title (e.g. 16-Core CPU)
    gpu_cores: Optional[int] = None  # Parsed from title (e.g. 40-Core GPU)


# ── Base scraper ──────────────────────────────────────────────────
class BaseScraper(ABC):
    """
    Every marketplace scraper must:
      1. Set self.source_name (e.g. "ebay")
      2. Set self.config (the global config)
      3. Implement scrape() to return list[ScrapedListing]
    
    This base class provides:
      - HTTP request helper (with rate limiting + user-agent rotation)
      - Spec parsers (RAM, storage, etc.)
      - Config access
    """
    
    def __init__(self, config: Config):
        """
        Initialize the scraper with the global configuration.
        
        Args:
            config: The Config object from config.py
        """
        self.config = config
        self.source_name = "base"  # Override in subclass
        
        # HTTP session — reuses connections for speed
        self.session = requests.Session()
        
        # Rotate user agent per request to avoid bot detection
        self._user_agents = [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        ]
        
        # Set default headers (overridden per request)
        self._update_headers()
    
    def _update_headers(self):
        """Rotate to a random user agent and set realistic browser headers."""
        ua = random.choice(self._user_agents)
        self.session.headers.update({
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            # Let requests/urllib3 manage Accept-Encoding automatically.
            # Explicitly setting "br" breaks if the brotli package is
            # not installed — requests returns raw compressed bytes.  
            "Sec-Ch-Ua": '"Not/A)Brand";v="99", "Google Chrome";v="125", "Chromium";v="125"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"macOS"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "Dnt": "1",
            "Connection": "keep-alive",
        })

    def fetch_with_playwright(self, url: str, timeout: int = 30000) -> str:
        """
        Fetch a page using Playwright (headless Chromium).
        
        Use this for sites that block plain requests with 403.
        Falls back to plain requests if Playwright is not installed.
        
        Args:
            url: The URL to fetch.
            timeout: Navigation timeout in milliseconds.
        
        Returns:
            The page HTML as a string.
        """
        try:
            from playwright.sync_api import sync_playwright
            
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox"],
                )
                context = browser.new_context(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US",
                )
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=timeout)
                page.wait_for_timeout(3000)
                html = page.content()
                browser.close()
                return html
        except Exception as e:
            raise Exception(f"Playwright failed: {e}") from e

    def fetch_page(self, url: str, max_retries: int = 3) -> str:
        """
        Fetch a web page and return its HTML.
        
        Includes a small delay (rate limiting) so we don't get
        blocked by the marketplace.
        
        Args:
            url: The full URL to fetch.
            max_retries: Number of retries on 403/5xx errors.
        
        Returns:
            The page HTML as a string.
        
        Raises:
            requests.RequestException if the fetch fails after all retries.
        """
        last_exception: Optional[Exception] = None
        
        for attempt in range(max_retries):
            # Rotate user agent on each attempt
            self._update_headers()
            
            # Wait 1-2 seconds between requests to be polite
            delay = 1.5 + random.random()
            time.sleep(delay)
            
            try:
                response = self.session.get(url, timeout=30)
                
                # If we got blocked (403), try again with different UA
                if response.status_code == 403:
                    print(f"  [{self.source_name}] 403 on attempt {attempt + 1}, retrying...")
                    last_exception = requests.HTTPError(f"403 Forbidden: {url}")
                    time.sleep(2)
                    continue
                
                response.raise_for_status()
                return response.text
                
            except requests.Timeout:
                print(f"  [{self.source_name}] Timeout on attempt {attempt + 1}, retrying...")
                last_exception = requests.Timeout(f"Timeout: {url}")
                time.sleep(2)
                continue
                
            except requests.ConnectionError as e:
                print(f"  [{self.source_name}] Connection error on attempt {attempt + 1}, retrying...")
                last_exception = e
                time.sleep(3)
                continue
                
            except requests.HTTPError as e:
                if attempt < max_retries - 1:
                    print(f"  [{self.source_name}] HTTP {e.response.status_code} on attempt {attempt + 1}")
                    time.sleep(2)
                    last_exception = e
                    continue
                raise
        
        raise last_exception or requests.RequestException(f"Failed after {max_retries} attempts: {url}")
    
    def parse_html(self, html: str) -> BeautifulSoup:
        """
        Parse HTML into a BeautifulSoup object for easy searching.
        
        Args:
            html: Raw HTML string.
        
        Returns:
            A BeautifulSoup object you can call .find() / .select() on.
        """
        return BeautifulSoup(html, "lxml")
    
    # ── Built-in spec parsers ──────────────────────────────────
    # These extract RAM, storage, etc. from listing titles.
    # They're available in every scraper via `self.extract_ram("...")`.
    
    @staticmethod
    def extract_ram(title: str) -> Optional[int]:
        """Extract RAM from a listing title."""
        return extract_ram_gb(title)
    
    @staticmethod
    def extract_storage(title: str) -> Optional[int]:
        """Extract storage from a listing title."""
        return extract_storage_gb(title)
    
    @staticmethod
    def extract_screen(title: str) -> Optional[float]:
        """Extract screen size from a listing title."""
        return extract_screen_size(title)
    
    @staticmethod
    def extract_chip(title: str) -> Optional[str]:
        """Extract chip name from a listing title."""
        return extract_chip(title)

    @staticmethod
    def extract_cores(title: str) -> tuple[Optional[int], Optional[int]]:
        """Extract (cpu_cores, gpu_cores) from a listing title."""
        return extract_core_counts(title)

    def parse_common_specs(self, title: str) -> dict:
        """
        Parse all the common ScrapedListing specs out of a title in one call.

        What: Delegates to the active product type's parse_specs()
        (see src/product_types/) and returns whatever dict it builds
        — for the "electronics" type (MacBook Pro / iPhone, the only
        one that exists today) that's "ram_gb", "storage_gb",
        "screen_size", "chip", "cpu_cores", "gpu_cores".

        How: Looks up PRODUCT_TYPES[self.config.search.product_type]
        and calls its parse_specs(title) — no parsing logic lives
        here directly.

        Why: Every scraper (ebay, swappa, apple_refurb, backmarket,
        mercari, bestbuy, offerup, newegg, gazelle) was repeating the
        same spec-extraction block before constructing a
        ScrapedListing; consolidating it here means there's exactly
        one place to touch if a new spec (or an entirely new product
        type, like apparel) ever needs parsing. Scrapers themselves
        never need to know or care which product type is active.

        Scrapers with special-case logic (e.g. swappa preferring an
        API-provided chip over the regex-parsed one, mercari falling
        back to a detail-page fetch for chip) should still call this
        method for the common fields and then override the relevant
        key(s) in the returned dict afterward.

        Args:
            title: The listing title to parse.

        Returns:
            Whatever dict the active product type's parse_specs()
            returns.
        """
        handler = PRODUCT_TYPES[self.config.search.product_type]
        return handler.parse_specs(title)

    # ── Filter method ──────────────────────────────────────────
    def passes_filters(self, listing: ScrapedListing) -> bool:
        """
        Check if a listing matches our search criteria.

        Checks are SKIPPED for any field set to None in config —
        this lets you loosen requirements without deleting fields.

        How: Universal checks (is this even the right product,
        location, price floor/ceiling) live here directly. Everything
        that varies by product category (chip/RAM/storage matching for
        electronics; whatever a future type needs) is delegated to
        PRODUCT_TYPES[search.product_type] — see src/product_types/.

        Args:
            listing: The parsed listing to check.

        Returns:
            True if we should keep this listing, False to skip it.
        """
        s = self.config.search
        handler = PRODUCT_TYPES[s.product_type]

        # Product-type-specific relevance check (rejects accessories,
        # off-topic listings, bad-condition red flags).
        if not handler.is_relevant(listing.title, s, listing.condition):
            return False

        # Product-type-specific spec matching (chip/RAM/storage/screen
        # for electronics; whatever fields a future type defines).
        if not handler.passes_type_filters(listing, s):
            return False

        # Check location (only if configured) — universal, not
        # product-type-specific.
        if s.location and listing.location:
            if s.location.lower() not in listing.location.lower():
                return False

        # Check price range — the floor is product-type-specific
        # (a real computer costs more than a real phone), the ceiling
        # is a universal budget cap from config.yaml.
        if listing.price_usd < handler.min_price_usd(s):
            return False
        if listing.price_usd > self.config.price.absolute_max_usd:
            return False

        return True
    
    # ── Abstract method — must implement in subclass ───────────
    @abstractmethod
    def scrape(self) -> list[ScrapedListing]:
        """
        Scrape the marketplace and return matching listings.
        
        Every scraper subclass MUST implement this method.
        
        Returns:
            A list of ScrapedListing objects matching our filters.
        """
        pass
