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
    location: Optional[str]    # City/state from the listing
    cpu_cores: Optional[int] = None  # Parsed from title (e.g. 16-Core CPU)
    gpu_cores: Optional[int] = None  # Parsed from title (e.g. 40-Core GPU)


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
    all_gb = re.findall(r'(\d+)\s*GB', title, re.IGNORECASE)
    for val_str in all_gb:
        val = int(val_str)
        if val in (8, 16, 24, 32, 36, 48, 64, 96, 128, 192):
            return val
    for val_str in all_gb:
        val = int(val_str)
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
        val = int(gb_storage.group(1))
        if val >= 256:
            return val
    
    # Pattern 3: "N GB" with N >= 256 (only storage is this big)
    all_gb = re.findall(r'(\d+)\s*GB', title, re.IGNORECASE)
    for val_str in all_gb:
        val = int(val_str)
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
    Also matches plain "M4", "M5" without suffix.

    Uses M\\d{1,2} (not a hardcoded M1-M5 range) so future chip
    generations (M6, M7, ...) parse correctly without a code change.
    """
    match = re.search(r'(M\d{1,2}\s*(?:Pro|Max|Ultra))', title, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    match = re.search(r'\b(M\d{1,2})\b', title, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def extract_core_counts(title: str) -> tuple[Optional[int], Optional[int]]:
    """
    Find CPU and GPU core counts in a listing title.

    Looks for Apple's standard spec phrasing, e.g.
    "16-Core CPU and 40-Core GPU" or "16 Core CPU / 40 Core GPU".

    Returns:
        (cpu_cores, gpu_cores) — either may be None if not found.
    """
    cpu_cores = None
    gpu_cores = None

    cpu_match = re.search(r'(\d+)[\s‑-]*Core\s*CPU', title, re.IGNORECASE)
    if cpu_match:
        cpu_cores = int(cpu_match.group(1))

    gpu_match = re.search(r'(\d+)[\s‑-]*Core\s*GPU', title, re.IGNORECASE)
    if gpu_match:
        gpu_cores = int(gpu_match.group(1))

    return cpu_cores, gpu_cores


ACCESSORY_KEYWORDS = [
    "case", "cover", "skin", "decals", "sticker", "sleeve", "bag",
    "charger", "adapter", "power cord", "cable", "hub", "docking",
    "keyboard", "mouse", "trackpad", "screen protector", "tempered glass",
    "stand", "mount", "arm", "holder", "tray", "shell", "hard shell",
    "battery", "replacement battery", "strap", "backpack",
    "logic board", "motherboard", "lcd", "display", "digitizer",
    "flex cable", "ribbon cable", "hinge", "palm rest", "top case",
    "bottom case", "fan", "speaker", "wrist rest", "bezel",
    "repair", "replacement", "parts", "for parts", "not working",
    "broken", "damaged", "for repair", "as-is", "as is",
    "screen only", "cracked", "water damage",
]

IPHONE_BAD_KEYWORDS = [
    "locked", "icloud", "activation lock",
    "for parts", "not working", "broken", "cracked", "damaged",
    "water damage", "for repair", "as is", "parts only",
    "repair needed", "stolen", "blacklisted",
    "hardware locked", "sim locked", "carrier locked",
    "network locked", "bad imei",
]

# Minimum price for a real computer (anything cheaper is an accessory/part)
MINIMUM_PRICE_USD = 200


def is_likely_macbook_pro(title: str) -> bool:
    """
    Check if a title is likely a real MacBook Pro (not an accessory).
    
    Filters out items like cases, chargers, keyboards that mention
    "MacBook" but aren't actual computers.
    
    A real MacBook Pro listing has:
      - "MacBook Pro" in the title (not just "MacBook")
      - No accessory keywords (case, charger, cable, etc.)
      - At least one hardware spec: chip (M1-M5), screen size, RAM,
        or storage
    
    Args:
        title: The listing title to check.
    
    Returns:
        True if this looks like an actual MacBook Pro computer.
    """
    title_lower = title.lower()
    
    # Must be a MacBook Pro (not just MacBook)
    if "macbook pro" not in title_lower:
        return False
    
    # Exclude accessories by keyword
    for kw in ACCESSORY_KEYWORDS:
        if kw in title_lower:
            return False
    
    # Must have at least one hardware indicator
    has_chip = bool(re.search(r'M\d{1,2}\s*(?:Pro|Max|Ultra)', title, re.IGNORECASE))
    has_screen = bool(re.search(r'\d{2}\s*[‑\-]?\s*inch', title, re.IGNORECASE)) or bool(re.search(r'\d{2}"', title))
    has_ram = bool(re.search(r'\d+\s*GB\s*(?:RAM|Memory|Unified)', title, re.IGNORECASE))
    has_storage = bool(re.search(r'\d+\s*(?:TB|GB)\s*(?:SSD|Storage)', title, re.IGNORECASE))
    
    if not (has_chip or has_screen or has_ram or has_storage):
        return False
    
    return True


def is_likely_iphone(title: str) -> bool:
    title_lower = title.lower()
    if "iphone" not in title_lower:
        return False
    locked = "locked" in title_lower and "unlocked" not in title_lower
    for kw in IPHONE_BAD_KEYWORDS:
        kw_lower = kw.lower()
        if kw_lower == "locked":
            continue
        if kw_lower in title_lower:
            return False
    if locked:
        return False
    return True


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

    @staticmethod
    def extract_cores(title: str) -> tuple[Optional[int], Optional[int]]:
        """Extract (cpu_cores, gpu_cores) from a listing title."""
        return extract_core_counts(title)
    
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
        title_lower = listing.title.lower()
        product_lower = s.product_name.lower()
        
        # Product-specific validation
        if "macbook" in product_lower:
            if not is_likely_macbook_pro(listing.title):
                return False
        elif "iphone" in product_lower:
            if not is_likely_iphone(listing.title):
                return False
        
        # Check chip (only if a chip filter is configured).
        # If chip_options is set (via a generation_family), it's a
        # rolling window of the last N flagship generations — match
        # against any of them instead of a fixed primary/fallback pair.
        if s.chip_options:
            if not listing.chip:
                return False
            listing_chip_lower = listing.chip.lower()
            if not any(opt.lower() in listing_chip_lower for opt in s.chip_options):
                return False
        elif s.chip:
            if not listing.chip:
                return False
            chip_primary = s.chip.lower()
            chip_primary_ok = chip_primary in listing.chip.lower()
            chip_fallback_ok = False
            if s.chip_fallback:
                chip_fallback_ok = s.chip_fallback.lower() in listing.chip.lower()
            if not (chip_primary_ok or chip_fallback_ok):
                return False

        # Check model generation keywords (only if configured, e.g. for
        # iPhone where the generation number lives in the title, not a
        # separately parsed field like chip).
        if s.model_keywords:
            if not any(kw.lower() in title_lower for kw in s.model_keywords):
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
        
        # Check storage minimum
        if s.storage_gb_min and listing.storage_gb:
            if listing.storage_gb < s.storage_gb_min:
                return False
        if s.storage_gb_max and listing.storage_gb:
            if listing.storage_gb > s.storage_gb_max:
                return False
        
        # Check location (only if configured)
        if s.location and listing.location:
            if s.location.lower() not in listing.location.lower():
                return False
        
        # Check price range
        min_price = 100 if "iphone" in product_lower else MINIMUM_PRICE_USD
        if listing.price_usd < min_price:
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
