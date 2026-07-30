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
import re
import time
from abc import ABC, abstractmethod
from typing import Optional
from dataclasses import dataclass

import requests
from bs4 import BeautifulSoup

from config import Config
from database import Listing


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


# ── Spec-parsing helpers ───────────────────────────────────────────
# These extract structured data from messy listing titles like:
#   "Apple MacBook Pro 14\" M5 Max Chip 128GB Memory 2TB SSD - Space Black"

def extract_ram_gb(title: str) -> Optional[int]:
    """
    Find RAM size in a listing title.
    
    Looks for patterns like "128GB", "128 GB", "64GB" near "RAM",
    "Memory", "Unified Memory", or "GB" of memory.
    
    Strategy:
      1. First try to match "N GB" near "RAM"/"Memory" keywords
         (most reliable).
      2. Fallback: match any "N GB" where N is a reasonable RAM
         size (8-256).  Higher numbers are typically storage.
    
    Returns:
        The RAM in GB (e.g. 128), or None if not found.
    """
    # Pattern 1: number GB followed by a RAM keyword
    patterns = [
        r'(\d+)\s*GB\s*(?:RAM|Memory|Unified\s*Memory)',
        r'(?:RAM|Memory|Unified\s*Memory)[:\s]*(\d+)\s*GB',
    ]
    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            val = int(match.group(1))
            if val <= 256:
                return val
    
    # Pattern 2: just "N GB" alone — but only if N is a reasonable
    # RAM size (not storage).  MacBook Pro RAM configs are:
    # 8, 16, 24, 32, 36, 48, 64, 96, 128, 192
    # Storage always starts at 256+ GB.
    generic_match = re.search(r'(\d+)\s*GB', title, re.IGNORECASE)
    if generic_match:
        val = int(generic_match.group(1))
        # Common RAM sizes: under 256
        if val <= 256:
            return val
    
    return None


def extract_storage_gb(title: str) -> Optional[int]:
    """
    Find storage (SSD) size in a listing title.
    
    Looks for patterns like "2TB", "2 TB", "512GB", "8TB SSD".
    
    Strategy:
      1. Match "N TB" (always storage).
      2. Match "N GB SSD" or "N GB Storage" (explicit).
      3. Match "N GB" where N >= 256 (storage sizes are always
         at least 256GB on MacBook Pros).
    
    Returns:
        The storage in GB (e.g. 2048 for 2TB), or None.
    """
    # Pattern 1: TB always means storage
    tb_match = re.search(r'(\d+)\s*TB\s*(?:SSD)?', title, re.IGNORECASE)
    if tb_match:
        return int(tb_match.group(1)) * 1024
    
    # Pattern 2: GB with explicit storage keyword
    gb_storage = re.search(
        r'(\d+)\s*GB\s*(?:SSD|Storage)', title, re.IGNORECASE
    )
    if gb_storage:
        return int(gb_storage.group(1))
    
    # Pattern 3: "N GB" with N >= 256 (only storage is this big)
    gb_generic = re.search(r'(\d+)\s*GB', title, re.IGNORECASE)
    if gb_generic:
        val = int(gb_generic.group(1))
        if val >= 256:
            return val
    
    return None


def extract_screen_size(title: str) -> Optional[float]:
    """
    Find screen size in a listing title.
    
    Looks for patterns like:
      - "14-inch", "14 inch", "14.2-inch"
      - '14"', '14.2"'
    """
    patterns = [
        r'(\d+(?:\.\d+)?)[\s-]*inch',   # "14-inch" or "14 inch"
        r'(\d+(?:\.\d+)?)"',             # '14"' or '14.2"'
    ]
    for pattern in patterns:
        match = re.search(pattern, title, re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def extract_chip(title: str) -> Optional[str]:
    """
    Find the chip name in a listing title.
    
    Looks for "M5 Max", "M4 Max", "M5 Pro", etc.
    """
    match = re.search(r'(M[345]\s*(?:Pro|Max|Ultra))', title, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


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
            "Accept-Encoding": "gzip, deflate, br",
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
        last_exception = None
        
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
    
    # ── Filter method ──────────────────────────────────────────
    def passes_filters(self, listing: ScrapedListing) -> bool:
        """
        Check if a listing matches our search criteria.
        
        Checks are SKIPPED for any field set to None in config —
        this lets you loosen requirements without deleting fields.
        
        Args:
            listing: The parsed listing to check.
        
        Returns:
            True if we should keep this listing, False to skip it.
        """
        s = self.config.search
        
        # Check chip (only if a chip filter is configured)
        if s.chip and listing.chip:
            chip_primary = s.chip.lower()
            chip_primary_ok = chip_primary in listing.chip.lower()
            chip_fallback_ok = False
            if s.chip_fallback:
                chip_fallback_ok = s.chip_fallback.lower() in listing.chip.lower()
            if not (chip_primary_ok or chip_fallback_ok):
                return False
        
        # Check screen size (only if screen_sizes is configured)
        if s.screen_sizes and listing.screen_size:
            size_ok = any(
                abs(listing.screen_size - size) < 1.0
                for size in s.screen_sizes
            )
            if not size_ok:
                return False
        
        # Check RAM (only if a RAM filter is configured)
        if s.ram_gb_primary and listing.ram_gb:
            ram_ok = (
                listing.ram_gb == s.ram_gb_primary
                or (s.ram_gb_fallback and listing.ram_gb == s.ram_gb_fallback)
            )
            if not ram_ok:
                return False
        
        # Check price ceiling
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
