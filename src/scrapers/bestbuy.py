# ─────────────────────────────────────────────────────────────────────
# Best Buy scraper — fetches Open Box MacBook listings
# ─────────────────────────────────────────────────────────────────────
# Best Buy sells "Open Box" items — products that were returned by
# customers and resold at a discount.  These can be excellent deals:
# sometimes 10-30% off retail for what's essentially a new product.
#
# WHY PLAYWRIGHT:
# Best Buy's search results are JavaScript-rendered.  Plain HTTP
# requests return an empty shell page.  We use Playwright to execute
# the JavaScript and get the fully-rendered HTML.
#
# WHAT WE SCRAPE:
# - Open Box MacBooks of various conditions (Excellent, Good, Fair).
# - Only items with "Open Box" in the title or metadata.
# - New/sealed items are excluded (those aren't deals).
#
# PARSING STRATEGY:
# Best Buy's HTML uses data-testid attributes for most elements.
# We try multiple CSS selectors to handle frontend changes.
# ─────────────────────────────────────────────────────────────────────

import re
from typing import Optional

from scrapers.base import BaseScraper, ScrapedListing
from config import Config


class BestBuyScraper(BaseScraper):
    """
    Scraper for Best Buy Open Box listings.

    BEST BUY OPEN BOX CONDITIONS:
    - "Open Box - Excellent": Like new, original packaging.
    - "Open Box - Good": Minor cosmetic damage, complete accessories.
    - "Open Box - Fair": Visible wear, may have missing accessories.

    All three are significantly cheaper than new and are covered by
    Best Buy's warranty policy.

    CHALLENGES:
    - Playwright is required (JavaScript rendering).
    - Class names change frequently (we try many selectors).
    - "Open Box" vs "New" filtering must be done post-parse because
      Best Buy doesn't have a dedicated Open Box search URL.
    """

    def __init__(self, config: Config):
        """
        Initialize the Best Buy scraper.

        Args:
            config: Global configuration with search parameters.
        """
        super().__init__(config)
        self.source_name = "bestbuy"

    def _fetch_search_page(self, url: str) -> Optional[str]:
        """
        Fetch a Best Buy search page using Playwright.

        WHY TWO-PAGE NAVIGATION:
        Best Buy sets cookies and session tokens on the homepage.
        Navigating directly to a search URL without visiting the
        homepage first often results in a CAPTCHA or empty results.
        We visit the homepage first, wait briefly, then go to the search.

        Args:
            url: The search URL to fetch (already includes query params).

        Returns:
            Full page HTML after JavaScript rendering, or None on failure.
        """
        try:
            # Import Playwright (optional dependency).
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                # Launch headless Chromium.
                browser = playwright.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-setuid-sandbox"],
                )
                # Create a realistic browser profile.
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/125.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1920, "height": 1080},
                    locale="en-US",
                )
                page = context.new_page()

                # Step 1: Visit homepage to establish session.
                page.goto(
                    "https://www.bestbuy.com",
                    wait_until="domcontentloaded",
                    timeout=15000,
                )
                # Wait for session cookies to be set.
                page.wait_for_timeout(2000)

                # Step 2: Navigate to the search URL.
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                # Wait for product cards to render (JavaScript + lazy loading).
                page.wait_for_timeout(5000)

                # Extract the fully-rendered HTML.
                html = page.content()
                browser.close()
                return html

        except Exception as e:
            print(f"  [Best Buy] Playwright fetch failed: {e}")
            return None

    def _build_search_url(self, screen_size: Optional[int]) -> str:
        """
        Build a Best Buy search URL for Open Box products.

        Args:
            screen_size: Optional screen size to narrow results.
                         e.g. 14 = "open box MacBook Pro 14-inch".

        Returns:
            Best Buy search URL sorted by price (low to high).
        """
        product = self.config.search.product_name
        if screen_size:
            query = f"open box {product} {screen_size}-inch"
        else:
            query = f"open box {product}"
        encoded_query = query.replace(" ", "+")
        return (
            f"https://www.bestbuy.com/site/searchpage.jsp"
            f"?st={encoded_query}"
            f"&sort=PRICE_LOW_TO_HIGH"
        )

    def _parse_listing_id(self, item, url: str) -> str:
        """
        Extract a unique listing ID from a Best Buy product item.

        Best Buy tags each product with a data-product-id attribute.
        We try that first, then fall back to the SKU in the URL,
        then finally a hash of the URL as last resort.

        Args:
            item: BeautifulSoup element for the product.
            url: The product URL string.

        Returns:
            A unique string identifier for this listing.
        """
        pid = item.get("data-product-id")
        if pid:
            return str(pid)
        # Try to extract SKU from URL path (e.g. /sku/6574321).
        match = re.search(r'/sku/(\d+)', url)
        if match:
            return match.group(1)
        return f"url_{hash(url)}"

    def _get_condition(self, item) -> Optional[str]:
        """
        Determine the Open Box condition of a Best Buy listing.

        BEST BUY'S OPEN BOX LABELING:
        Best Buy doesn't have a dedicated Open Box section in search.
        Instead, Open Box items are mixed in with regular listings.
        We determine if an item is Open Box by checking:
        1. The URL contains "/openbox".
        2. The price block has Open Box badging text.
        3. Specific Open Box messaging elements exist.
        4. The full item text contains "Open Box".

        Args:
            item: BeautifulSoup element for the product.

        Returns:
            Condition string (e.g. "Open-Box - Excellent")
            or None if this is a new/sealed item.
        """
        # Check if the product URL indicates Open Box.
        link_el = item.select_one("a.product-list-item-link")
        if link_el:
            href = link_el.get("href", "")
            if "/openbox" in href:
                return "Open-Box"
        # Check for Open Box badging in the price section.
        badge = item.select_one('[data-testid="price-block-badging-text"]')
        if badge:
            text = badge.get_text(strip=True)
            if "open" in text.lower():
                return "Open-Box"
        # Check for specific Open Box condition messaging.
        cond = item.select_one(
            '[data-testid*="open-box-sku-messaging"] .font-weight-medium'
        )
        if cond:
            text = cond.get_text(strip=True)
            if text:
                return text
        # Last resort: check the full item text.
        full_text = item.get_text(" ", strip=True)
        if "Open Box" in full_text or "Open-Box" in full_text:
            return "Open-Box"
        return None

    def _parse_single_item(self, item) -> Optional[ScrapedListing]:
        """
        Parse a single Best Buy product item into a ScrapedListing.

        Args:
            item: BeautifulSoup element representing a product list item.

        Returns:
            ScrapedListing object, or None if parsing fails.
        """
        # Extract the product title.
        title_el = item.select_one("h3.product-title")
        if not title_el:
            return None
        title = title_el.get_text(strip=True)
        # Only process MacBook listings.
        if not title or "MacBook" not in title:
            return None

        # Extract the product URL.
        link_el = item.select_one("a.product-list-item-link")
        if not link_el:
            return None
        url = link_el.get("href", "")
        if url.startswith("/"):
            url = "https://www.bestbuy.com" + url

        # Determine if this is an Open Box item and its condition.
        condition = self._get_condition(item)
        if not condition:
            # Skip non-Open Box items.
            return None

        # Extract the price.
        price_el = item.select_one(
            '[data-testid="price-block-customer-price"] .font-500'
        )
        if not price_el:
            return None
        price_text = price_el.get_text(strip=True)
        price_text = price_text.replace("$", "").replace(",", "")
        price_match = re.search(r'(\d+(?:\.\d{2})?)', price_text)
        if not price_match:
            return None
        price = float(price_match.group(1))

        # Generate a unique listing ID.
        listing_id = self._parse_listing_id(item, url)

        # Extract specs from the title string.
        ram = self.extract_ram(title)
        storage = self.extract_storage(title)
        screen = self.extract_screen(title)
        chip = self.extract_chip(title)
        cpu_cores, gpu_cores = self.extract_cores(title)

        # Special case: Best Buy sometimes puts RAM in the URL path
        # (e.g. "128GB" in URL = 128GB RAM for Mac Pro).
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
            location=None,
            cpu_cores=cpu_cores,
            gpu_cores=gpu_cores,
        )

    def scrape(self) -> list[ScrapedListing]:
        """
        Main entry point: fetch and parse all Best Buy Open Box listings.

        STRATEGY:
        1. Build search URLs for each configured screen size.
        2. Fetch each page using Playwright.
        3. Parse listing items from the rendered HTML.
        4. Filter to only Open Box items.
        5. Apply user filters (price, condition, etc.).
        6. Deduplicate by listing_id.

        Returns:
            List of ScrapedListing objects matching the search criteria.
        """
        found: list[ScrapedListing] = []
        found_ids: set = set()
        screen_sizes = self.config.search.screen_sizes
        sizes_to_search = screen_sizes if screen_sizes else [None]

        for screen_size in sizes_to_search:
            search_url = self._build_search_url(screen_size)
            html = self._fetch_search_page(search_url)
            if not html:
                continue
            soup = self.parse_html(html)

            # Try multiple selectors for product list items.
            items = soup.select("li.product-list-item")
            if not items:
                items = soup.select(".product-list-item")

            results_for_size = 0
            max_results = self.config.search.results_per_size

            for item in items:
                if results_for_size >= max_results:
                    break
                try:
                    listing = self._parse_single_item(item)
                    if listing and listing.listing_id not in found_ids:
                        if self.passes_filters(listing):
                            found.append(listing)
                            found_ids.add(listing.listing_id)
                            results_for_size += 1
                except Exception:
                    # Skip individual parse errors.
                    continue

        print(f"  [Best Buy] Found {len(found)} matching Open Box listings")
        return found
