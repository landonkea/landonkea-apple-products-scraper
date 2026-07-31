# ─────────────────────────────────────────────────────────────────────
# Back Market scraper — fetches refurbished MacBook listings
# ─────────────────────────────────────────────────────────────────────
# Back Market is a French marketplace specializing in refurbished
# electronics.  It's one of the largest refurbished marketplaces in
# Europe and the US.
#
# WHY PLAYWRIGHT + STEALTH:
# Back Market aggressively blocks automated requests (even with proper
# headers).  They use Cloudflare and JavaScript challenge pages.
# Plain requests (via `requests` library) always get blocked.
#
# Our strategy:
#   1. Try Playwright with stealth plugin first (evades detection).
#   2. If that fails, try normal Playwright.
#   3. If that also fails, try a plain HTTP request as last resort.
#
# NOTE: Back Market listings are all "Refurbished" — there's no
# condition variation like "Good" / "Mint" / "Fair".
# ─────────────────────────────────────────────────────────────────────

import re
from typing import Optional

from config import Config
from scrapers.base import BaseScraper, ScrapedListing


class BackMarketScraper(BaseScraper):
    """
    Scraper for Back Market refurbished electronics marketplace.

    WHY A MULTI-LAYER FETCH STRATEGY:
    Back Market uses aggressive bot detection.  We try three approaches
    in descending order of stealth:
      1. Playwright + stealth plugin (hardest to detect).
      2. Plain Playwright (moderate detection risk).
      3. Plain HTTP requests (most likely to be blocked).

    PARSING STRATEGY:
    Back Market renders listings as <article> cards with:
      - A data-testid="product-title" span for the title.
      - A data-qa="productCardPrice" element for the price.
      - An h3 > a element for the listing URL.
    We try multiple CSS selectors in case their class names change
    (Back Market frequently updates their frontend).
    """

    def __init__(self, config: Config):
        """
        Initialize the Back Market scraper.

        Args:
            config: Global configuration with search parameters.
        """
        # Call parent constructor for shared utilities (rate limiting, etc.).
        super().__init__(config)
        # Source identifier used for deduplication across scrapers.
        self.source_name = "backmarket"

    def _build_search_url(self, screen_size: Optional[int]) -> str:
        """
        Build a Back Market search URL for the configured product.

        Args:
            screen_size: Optional screen size to include in the query
                        (e.g. 14 for "14-inch").  Helps narrow results.

        Returns:
            Full search URL with query parameters.
        """
        product = self.config.search.product_name
        if screen_size:
            # Include screen size in the query to filter results server-side.
            query = f"{product} {screen_size}-inch"
        else:
            query = product
        # URL-encode the query by replacing spaces with +.
        encoded = query.replace(" ", "+")
        return f"https://www.backmarket.com/search?q={encoded}"

    def _fetch_with_stealth(self, search_url: str) -> str:
        """
        Fetch a page using Playwright with the stealth plugin.

        The stealth plugin modifies browser fingerprint attributes
        (WebGL, fonts, navigator properties) to make headless Chrome
        look like a real user's browser.  This is our best bet against
        Back Market's bot detection.

        WORKFLOW:
        1. Start a stealth-enabled Playwright session.
        2. Visit the homepage first (creates cookies/session).
        3. Wait 3 seconds for session to establish.
        4. Navigate to the actual search URL.
        5. Wait 8 seconds for JavaScript rendering + dynamic content.
        6. Extract the fully-rendered HTML.

        Args:
            search_url: The Back Market search URL to fetch.

        Returns:
            Full page HTML after JavaScript execution.

        Raises:
            Exception: If Playwright fails at any step.
        """
        try:
            # Import Playwright libraries (they're optional dependencies).
            from playwright.sync_api import sync_playwright
            from playwright_stealth import Stealth

            # Use the Stealth context manager which wraps Playwright's
            # sync_playwright() and applies stealth modifications.
            with Stealth().use_sync(sync_playwright()) as playwright:
                # Launch a headless Chromium browser with anti-detection args.
                browser = playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                # Create a new browser context with a realistic user profile.
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

                # Step 1: Visit the homepage to establish a session.
                page.goto(
                    "https://www.backmarket.com",
                    wait_until="domcontentloaded",
                    timeout=15000,
                )
                # Wait for any JavaScript redirects or cookie banners.
                page.wait_for_timeout(3000)

                # Step 2: Navigate to the actual search page.
                page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                # Wait for product cards to render (lazy-loaded content).
                page.wait_for_timeout(8000)

                # Step 3: Extract the fully-rendered HTML.
                html = page.content()
                browser.close()
                return html

        except Exception as e:
            raise Exception(f"Playwright stealth failed: {e}") from e

    def _slug_to_title(self, slug: str) -> str:
        """
        Convert a URL slug to a human-readable product title.

        Back Market uses URL slugs like "/p/macbook-pro-14-m3-2023-512gb".
        This method converts those back to readable titles like
        "Macbook pro 14 m3 2023 512GB".

        Args:
            slug: The URL slug (e.g. "macbook-pro-14-m3-2023-512gb").

        Returns:
            A cleaned-up product title string.
        """
        # Split the slug by "/" and take the relevant part.
        parts = slug.split("/")
        if len(parts) >= 3:
            slug = parts[2]
        slug = slug.split("/")[0] if "/" in slug else slug
        # Replace hyphens with spaces to create a readable title.
        title = slug.replace("-", " ")
        # Normalize common abbreviations to uppercase.
        title = (
            title.replace("gb", "GB")
            .replace("ssd", "SSD")
            .replace("ram", "RAM")
            .replace("gpu", "GPU")
        )
        # Capitalize the first word.
        words = title.split()
        if words:
            words[0] = words[0].capitalize()
        return " ".join(words)

    def scrape(self) -> list[ScrapedListing]:
        """
        Main entry point: fetch and parse all Back Market listings.

        STRATEGY:
        1. Build search URLs for each configured screen size.
        2. Try fetching with Playwright + stealth (best chance).
        3. Fall back to plain Playwright, then plain HTTP.
        4. Parse listing cards from the HTML.
        5. Apply user filters (price, condition).
        6. Deduplicate by listing_id.

        Returns:
            List of ScrapedListing objects matching the search criteria.
        """
        found: list[ScrapedListing] = []
        found_ids: set = set()

        # Determine which screen sizes to search.
        screen_sizes = self.config.search.screen_sizes
        sizes_to_search = screen_sizes if screen_sizes else [None]

        # Iterate over each screen size (or just one pass if no size filter).
        for screen_size in sizes_to_search:
            url = self._build_search_url(screen_size)
            html = None

            # Try three fetch strategies in descending order of sophistication.
            # This ensures we get results even if Back Market changes their
            # bot detection.
            try:
                html = self._fetch_with_stealth(url)
            except Exception as e:
                print(f"  [Back Market] Playwright stealth failed: {e}, trying normal Playwright...")
                try:
                    # Fall back to the base scraper's Playwright method.
                    html = self.fetch_with_playwright(url)
                except Exception as e2:
                    print(f"  [Back Market] Normal Playwright also failed: {e2}, trying plain request...")
                    try:
                        # Last resort: plain HTTP request (will likely fail).
                        html = self.fetch_page(url)
                    except Exception as e3:
                        print(f"  [Back Market] All methods failed: {e3}")
                        continue

            if not html:
                continue
            soup = self.parse_html(html)

            # Try multiple CSS selectors for listing cards.
            # Back Market frequently changes their class names.
            # We try the most specific selectors first, then fall back to
            # more generic ones.
            cards = soup.select("article[data-spec='product-card-content']")
            if not cards:
                cards = soup.select("article._cardContainer")
            if not cards:
                cards = soup.select("[class*='_cardContainer_']")
            if not cards:
                # Last resort: any <article> tag on the page.
                cards = soup.find_all("article")

            results_for_size = 0
            max_results = self.config.search.results_per_size

            # Parse each listing card.
            for card in cards:
                if results_for_size >= max_results:
                    break
                try:
                    listing = self._parse_card(card)
                    if listing and listing.listing_id not in found_ids:
                        if self.passes_filters(listing):
                            found.append(listing)
                            found_ids.add(listing.listing_id)
                            results_for_size += 1
                except Exception:
                    # Skip individual card parse errors.
                    continue

        print(f"  [Back Market] Found {len(found)} matching listings")
        return found

    def _parse_card(self, card) -> ScrapedListing | None:
        """
        Extract listing data from a single Back Market listing card.

        Args:
            card: A BeautifulSoup element representing a product card.

        Returns:
            A ScrapedListing object, or None if the card couldn't be parsed.
        """
        # Extract the product title from the data-testid span.
        title_elem = card.select_one("span[data-testid='product-title']")
        if not title_elem:
            return None

        display_title = title_elem.get_text(strip=True)
        if not display_title:
            return None

        # Extract the listing URL and slug from the anchor tag.
        link_elem = card.select_one("h3 a")
        url = ""
        slug = ""
        if link_elem:
            href = link_elem.get("href", "")
            if href:
                url = href
                if not url.startswith("http"):
                    url = f"https://www.backmarket.com{url}"
                # Extract the slug from the URL path (e.g. "/p/macbook-pro-...").
                slug_match = re.search(r"/p/([^/?]+)", href)
                if slug_match:
                    slug = slug_match.group(1)

        # Use slug-derived title (cleaner) or fall back to display title.
        title = self._slug_to_title(slug) if slug else display_title

        # Extract the price from the productCardPrice element.
        price_el = card.select_one("[data-qa='productCardPrice'] .heading-2")
        if not price_el:
            price_el = card.select_one("[data-qa='productCardPrice']")
        if not price_el:
            return None

        # Clean the price text (remove $, commas, spaces) and parse as float.
        price_text = price_el.get_text(strip=True)
        price_text = price_text.replace("$", "").replace(",", "").replace(" ", "")
        price_match = re.search(r'(\d+(?:\.\d{2})?)', price_text)
        if not price_match:
            return None
        price = float(price_match.group(1))

        # Back Market only sells refurbished — no condition variation.
        condition = "Refurbished"

        # Generate a unique listing ID from URL or title hash.
        listing_id = f"bm_{hash(url or title)}"

        # Extract specs from the title string.
        ram = self.extract_ram(title)
        storage = self.extract_storage(title)
        screen = self.extract_screen(title)
        chip = self.extract_chip(title)
        cpu_cores, gpu_cores = self.extract_cores(title)

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
