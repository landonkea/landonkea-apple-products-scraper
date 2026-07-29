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
        
        # Custom headers so websites think we're a real browser
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
    
    def fetch_page(self, url: str) -> str:
        """
        Fetch a web page and return its HTML.
        
        Includes a small delay (rate limiting) so we don't get
        blocked by the marketplace.
        
        Args:
            url: The full URL to fetch.
        
        Returns:
            The page HTML as a string.
        
        Raises:
            requests.RequestException if the fetch fails.
        """
        # Wait 1-2 seconds between requests to be polite
        time.sleep(1.5)
        
        response = self.session.get(url, timeout=30)
        response.raise_for_status()  # Raise error if 404, 500, etc.
        return response.text
    
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
        
        This checks:
          - Chip matches M5 Max
          - Screen size is 14-inch
          - RAM is 128GB (primary) or 64GB (fallback)
          - Price is under absolute_max_usd
        
        Args:
            listing: The parsed listing to check.
        
        Returns:
            True if we should keep this listing, False to skip it.
        """
        config = self.config.search
        
        # Check chip (most important filter)
        if listing.chip:
            chip_ok = (
                config.chip.lower() in listing.chip.lower()
            )
            if not chip_ok:
                return False
        
        # Check screen size
        if listing.screen_size:
            size_ok = (
                abs(listing.screen_size - config.screen_size_inches) < 1.0
            )
            if not size_ok:
                return False
        
        # Check RAM
        if listing.ram_gb:
            ram_ok = (
                listing.ram_gb == config.ram_gb_primary
                or listing.ram_gb == config.ram_gb_fallback
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
