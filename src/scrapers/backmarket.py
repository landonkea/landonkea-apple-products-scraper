# ─────────────────────────────────────────────────────────────────────
# Back Market scraper — fetches refurbished MacBook/iPhone listings
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
# WHY A TWO-STEP "DISCOVER THEN FETCH" PROCESS (same shape as Swappa):
# Back Market's `/search?q=...` page no longer renders individual
# purchasable listings.  Each card on that page is now a CATEGORY tile
# — one per chip generation (e.g. "MacBook Pro (M5 series)") or, for
# iPhone, one per specific config — showing a single "starting at"
# price with no parseable condition/RAM/storage breakdown.  Those tiles
# link to a `/p/{slug}/{uuid}` product page for one representative
# config of that generation.
#
# That product page is a configurator: it embeds Apple's own condition
# grades (Fair/Good/Excellent/Premium) *and* sibling config pickers
# (screen size, RAM, storage, processor tier) directly in a Nuxt.js
# `__NUXT_DATA__` JSON payload, each with its own real price and
# product ID -- i.e. genuine purchasable listings, not aggregates.  So
# we fetch the search page to discover candidate product pages
# (`_discover_generation_links`), then fetch each product page and pull
# every variant it exposes out of that embedded JSON
# (`_extract_variant_offers`).  This mirrors Swappa's
# `_discover_variant_slugs` / `_fetch_listings_for_slug` split: one
# step finds candidate pages, the other extracts real listings from
# each one.
#
# NOTE: Back Market listings are all "Refurbished" at the product-type
# level, but DO have real per-listing condition variation (Fair/Good/
# Excellent/Premium) once you're on a product page -- that's exactly
# what this scraper now surfaces instead of collapsing to one
# "Refurbished" bucket.
# ─────────────────────────────────────────────────────────────────────

import json
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
    `_fetch_with_fallback()` wraps this chain so both the search page
    fetch and every product-page fetch reuse the same fallback logic.

    DISCOVER-THEN-FETCH STRATEGY:
    1. Fetch the search page for the configured product (per screen
       size, if any) and discover the product-page links behind each
       category tile (`_discover_generation_links`).
    2. Fetch each discovered product page and pull every purchasable
       variant (condition x screen x RAM x storage combination) out of
       its embedded Nuxt.js state (`_extract_variant_offers`).
    3. Convert each variant into a ScrapedListing and let
       `passes_filters()` (from BaseScraper) do all the actual
       chip/RAM/storage/screen/price filtering -- this scraper does no
       bespoke filtering of its own.
    """

    # Hard cap on how many product-page detail fetches we'll do per
    # scrape run.  Each fetch launches a fresh headless-Chromium
    # session (homepage warm-up + navigation + render wait is 10+
    # seconds), so following every tile on a broad search (Back Market
    # can return 30+ cards for "iPhone Pro Max") unconditionally would
    # make a single scrape take many minutes.  This bounds runtime; it
    # is a breadth cap, not a spec filter -- passes_filters() still
    # does the real filtering on whatever variants we do fetch.
    MAX_DETAIL_PAGES = 12

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
            search_url: The Back Market URL to fetch (search page or
                        product page -- this works for both).

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

                # Step 2: Navigate to the actual target page.
                page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
                # Wait for content to render (lazy-loaded / hydrated content).
                page.wait_for_timeout(8000)

                # Step 3: Extract the fully-rendered HTML.
                html = page.content()
                browser.close()
                return html

        except Exception as e:
            raise Exception(f"Playwright stealth failed: {e}") from e

    def _fetch_with_fallback(self, url: str, label: str) -> Optional[str]:
        """
        Fetch a URL trying stealth Playwright, then plain Playwright,
        then plain HTTP, in that order.

        WHAT: A single reusable wrapper around the three-tier fetch
        strategy described in the module docstring.

        HOW: Tries `_fetch_with_stealth()` first; on failure falls back
        to the base scraper's `fetch_with_playwright()`; on failure
        falls back to `fetch_page()` (plain `requests`, which is known
        to get a 403 from Back Market on its own but is kept as a
        last-ditch attempt in case bot detection is ever relaxed).

        WHY A SHARED HELPER: Both the search-page fetch and every
        product-page fetch need this exact fallback chain. Previously
        this scraper only fetched the search page, so the chain lived
        inline in `scrape()`; now that we fetch N product pages too,
        duplicating the three-way try/except per call site would bloat
        `scrape()` and risk the two copies drifting apart.

        Args:
            url: The URL to fetch.
            label: A short human-readable label used in log/error
                   messages so failures are traceable to which fetch
                   (e.g. the search page vs. a specific product page).

        Returns:
            The page HTML, or None if every fetch method failed.
        """
        try:
            return self._fetch_with_stealth(url)
        except Exception as e:
            print(f"  [Back Market] Stealth fetch failed for {label}: {e}, trying normal Playwright...")
        try:
            return self.fetch_with_playwright(url)
        except Exception as e2:
            print(f"  [Back Market] Normal Playwright also failed for {label}: {e2}, trying plain request...")
        try:
            return self.fetch_page(url)
        except Exception as e3:
            print(f"  [Back Market] All fetch methods failed for {label}: {e3}")
            return None

    def _slug_to_title(self, slug: str) -> str:
        """
        Convert a URL slug to a human-readable product title.

        Back Market uses URL slugs like "macbook-pro-14-m3-2023-512gb".
        This method converts those back to readable titles like
        "Macbook pro 14 m3 2023 512GB".

        Args:
            slug: The URL slug (e.g. "macbook-pro-14-m3-2023-512gb").
                  May also be a full path fragment containing slashes;
                  only the last path segment is used.

        Returns:
            A cleaned-up product title string.
        """
        # If a full path was passed in, use only the last segment.
        slug = slug.rstrip("/").split("/")[-1]

        # Back Market slugs spell the 1TB/2TB/4TB/8TB storage tiers as
        # a raw decimal GB figure -- "...-ssd-1000gb" rather than
        # "...-ssd-1tb". extract_storage_gb() (base.py) only converts
        # a "N TB" figure to GB (N * 1024); a literal "1000gb" parses
        # as exactly 1000, which is a hair under a 1024+ GB ("1TB
        # minimum") filter threshold even though it's the same real
        # 1TB config every other marketplace's listing titles spell
        # out as "1TB". Normalize those round-thousand GB figures back
        # to "N TB" here so this scraper's titles are parsed the same
        # way as every other marketplace's.
        slug = re.sub(r"(\d+)000gb", r"\1tb", slug, flags=re.IGNORECASE)

        # Back Market also drops the decimal point from the 14.2"/16.2"
        # MacBook Pro screen sizes in slugs -- "...-2023-142-inch-..."
        # instead of "...-2023-14.2-inch-...". extract_screen_size()
        # would otherwise parse that as a 142-inch screen (way outside
        # any real screen_sizes filter) instead of matching the 14"
        # bucket it actually is. MacBook Pro screen sizes are always a
        # 2-digit whole-inch figure, so a 3-digit number directly
        # before "-inch" unambiguously means the decimal got dropped.
        slug = re.sub(r"(\d{2})(\d)-inch", r"\1.\2-inch", slug, flags=re.IGNORECASE)

        # Replace hyphens with spaces to create a readable title.
        title = slug.replace("-", " ")
        # Normalize common abbreviations to uppercase.
        title = (
            title.replace("gb", "GB")
            .replace("tb", "TB")
            .replace("ssd", "SSD")
            .replace("ram", "RAM")
            .replace("gpu", "GPU")
        )
        # Capitalize the first word.
        words = title.split()
        if words:
            words[0] = words[0].capitalize()
        return " ".join(words)

    def _discover_generation_links(self, soup) -> list[str]:
        """
        Find product-page links behind every relevant category tile on
        a Back Market search results page.

        WHAT: Back Market's search page now renders one aggregate
        "starting at" tile per chip generation (or per specific config,
        for iPhone) instead of individual listings. Each tile's title
        links to a `/p/{slug}/{uuid}` product page. This method
        collects those product-page URLs.

        HOW: Tries the same cascade of CSS selectors the old card
        parser used (Back Market changes class names often), reads
        each card's title span to cheaply discard obviously-irrelevant
        tiles (accessories like cases/sleeves that mention the product
        name but aren't the product itself), then pulls the `h3 a`
        link's href. Tracking query params (e.g. `?l=12`) are stripped
        so the same underlying product page discovered via different
        screen-size searches collapses to a single URL.

        WHY A SEPARATE DISCOVERY STEP: Same reasoning as Swappa's
        `_discover_variant_slugs` -- the search page tells us *which*
        product pages exist for the generations Back Market currently
        has in stock, but doesn't itself contain real listing data
        anymore. Isolating discovery here keeps it independently
        testable and separate from the per-page fetch/parse step in
        `_extract_variant_offers`.

        Args:
            soup: Parsed BeautifulSoup of the search results page.

        Returns:
            A list of unique, absolute product-page URLs.
        """
        cards = soup.select("article[data-spec='product-card-content']")
        if not cards:
            cards = soup.select("article._cardContainer")
        if not cards:
            cards = soup.select("[class*='_cardContainer_']")
        if not cards:
            # Last resort: any <article> tag on the page.
            cards = soup.find_all("article")

        product = self.config.search.product_name.lower()
        # Crude "is this even the right product line" gate -- catches
        # accessory tiles (cases, screen protectors, sleeves) that
        # mention the product name but aren't the product itself,
        # before we spend a Playwright fetch on them. This is NOT the
        # real spec/condition/price filtering -- that happens later,
        # in passes_filters(), once we have an actual parsed listing.
        if "macbook" in product:
            keyword = "macbook pro"
        elif "iphone" in product:
            keyword = "iphone"
        else:
            keyword = product

        links: list[str] = []
        seen: set = set()
        for card in cards:
            title_el = card.select_one(
                "span[data-testid='product-title'], span[data-test='product-title']"
            )
            title = title_el.get_text(strip=True) if title_el else ""
            if keyword not in title.lower():
                continue

            link_el = card.select_one("h3 a")
            if not link_el:
                continue
            href = link_el.get("href", "")
            if not href:
                continue

            url = href if href.startswith("http") else f"https://www.backmarket.com{href}"
            # Drop tracking/query params so the same product page
            # found from multiple searches (e.g. both the 14" and 16"
            # MacBook searches) dedupes to one fetch.
            url = url.split("?")[0]

            if url in seen:
                continue
            seen.add(url)
            links.append(url)

        return links

    def _extract_variant_offers(self, html: str) -> list[dict]:
        """
        Pull every purchasable variant out of a Back Market product
        page's embedded Nuxt.js application state.

        WHAT: A Back Market product page (`/p/{slug}/{uuid}`) is a
        configurator: alongside the currently-selected config, it also
        embeds every sibling option exposed by its pickers (condition
        grade, screen size, RAM, storage, processor tier) directly in
        a `<script id="__NUXT_DATA__">` JSON payload -- each with its
        own real product ID, URL slug, and price. Those are genuine
        individual listings, not an aggregate.

        HOW: Nuxt serializes its app state as a flat array where
        integers are indices into that same array (a compact
        deduplicated-reference format, not a plain tree) -- objects
        reference their field values by index rather than embedding
        them inline. We scan the array for every dict entry shaped
        like a picker "item" (has `label`, `productId`, `price`,
        `slug`, and `parameters` keys) and resolve its referenced
        values a few levels deep. Recursion is depth-capped and skips
        the `available`/`acquirable` keys specifically, because those
        point into the page's live Vue reactive store (global app
        state, e.g. cart/i18n/session), which is enormous and
        self-referential -- resolving it isn't needed for listing data
        and would otherwise blow up traversal time. Each item's
        `parameters.grade.name` (when present) gives the real condition
        for that specific price point, since non-condition pickers
        (screen/RAM/storage/color) still report whichever grade is
        selected by default.

        WHY THIS INSTEAD OF A DEDICATED "grades" PICKER LOOKUP: An
        earlier version of this method looked specifically for the
        "Condition" grade picker. That works but only surfaces
        Fair/Good/Excellent/Premium of the ONE config the tile happened
        to link to (e.g. a base M5 chip, not M5 Max). Scanning for
        every picker-shaped item instead also picks up sibling configs
        exposed on the same page (e.g. a 16" M5 Pro variant surfaced by
        the screen-size picker) -- more real listings from the same
        single fetch, with passes_filters() left to decide which ones
        actually match the configured chip/RAM/storage/screen target.

        Args:
            html: Raw HTML of a Back Market product page.

        Returns:
            A list of dicts with keys: product_id, slug, price,
            condition. Empty list if the page has no `__NUXT_DATA__`
            script or it doesn't parse as JSON.
        """
        soup = self.parse_html(html)
        script = soup.find("script", id="__NUXT_DATA__")
        if not script or not script.string:
            return []

        try:
            data = json.loads(script.string)
        except (json.JSONDecodeError, TypeError):
            return []

        if not isinstance(data, list):
            return []

        # Reactive-store keys that point into huge/circular global app
        # state (cart, i18n, session...) -- irrelevant to listing data
        # and expensive to walk, so we never follow them.
        skip_keys = {"available", "acquirable"}

        def resolve(i: int, depth: int = 0):
            """Resolve a Nuxt payload index to its real value, a few levels deep."""
            if depth > 4 or not (0 <= i < len(data)):
                return None
            v = data[i]
            if isinstance(v, int) and 0 <= v < len(data) and v != i:
                return resolve(v, depth + 1)
            if isinstance(v, dict):
                return {
                    k: (resolve(x, depth + 1) if isinstance(x, int) else x)
                    for k, x in v.items()
                    if k not in skip_keys
                }
            return v

        offers: dict[tuple, dict] = {}
        required_keys = {"label", "productId", "price", "slug", "parameters"}
        for idx, v in enumerate(data):
            if not (isinstance(v, dict) and required_keys <= v.keys()):
                continue

            item = resolve(idx)
            if not isinstance(item, dict):
                continue

            product_id = item.get("productId")
            slug = item.get("slug")
            price_info = item.get("price")
            if not (
                isinstance(product_id, str)
                and isinstance(slug, str)
                and isinstance(price_info, dict)
            ):
                continue

            try:
                price = float(price_info.get("amount"))
            except (TypeError, ValueError):
                continue

            # Read the real condition grade for this specific price
            # point out of the item's own parameters, falling back to
            # a generic label if it's genuinely missing.
            condition = "Refurbished"
            params = item.get("parameters")
            if isinstance(params, dict) and isinstance(params.get("grade"), dict):
                grade_name = params["grade"].get("name")
                if isinstance(grade_name, str) and grade_name:
                    condition = grade_name

            key = (product_id, condition, slug)
            if key not in offers:
                offers[key] = {
                    "product_id": product_id,
                    "slug": slug,
                    "price": price,
                    "condition": condition,
                }

        return list(offers.values())

    def _offer_to_listing(self, offer: dict) -> Optional[ScrapedListing]:
        """
        Convert one raw variant offer (from `_extract_variant_offers`)
        into a ScrapedListing.

        Args:
            offer: Dict with keys product_id, slug, price, condition.

        Returns:
            A ScrapedListing, or None if the offer has no usable slug.
        """
        slug = offer.get("slug")
        if not slug:
            return None

        title = self._slug_to_title(slug)
        if not title:
            return None

        url = f"https://www.backmarket.com/en-us/p/{slug}/{offer['product_id']}"
        # Include the condition in the ID: the same product_id can
        # appear at multiple grades/prices (Fair/Good/Excellent/
        # Premium of one config), and those are distinct listings.
        listing_id = f"bm_{offer['product_id']}_{offer['condition']}"

        specs = self.parse_common_specs(title)

        return ScrapedListing(
            source=self.source_name,
            listing_id=listing_id,
            title=title,
            price_usd=offer["price"],
            url=url,
            condition=offer["condition"],
            ram_gb=specs["ram_gb"],
            storage_gb=specs["storage_gb"],
            screen_size=specs["screen_size"],
            chip=specs["chip"],
            location=None,
            cpu_cores=specs["cpu_cores"],
            gpu_cores=specs["gpu_cores"],
        )

    def scrape(self) -> list[ScrapedListing]:
        """
        Main entry point: fetch and parse all Back Market listings.

        STRATEGY (discover then fetch -- see module docstring):
        1. Fetch the search page for each configured screen size (or
           once, generically, if no screen size is configured) and
           discover the product-page links behind each category tile.
        2. Fetch up to `MAX_DETAIL_PAGES` of those product pages and
           extract every real purchasable variant embedded in each.
        3. Convert each variant to a ScrapedListing and apply
           `passes_filters()` (price, chip, RAM, storage, condition,
           etc. -- all inherited from BaseScraper, no bespoke logic
           here).
        4. Deduplicate by listing_id.

        Returns:
            List of ScrapedListing objects matching the search criteria.
        """
        found: list[ScrapedListing] = []
        found_ids: set = set()

        # ── Step 1: discover candidate product-page links ──────────
        screen_sizes = self.config.search.screen_sizes
        sizes_to_search = screen_sizes if screen_sizes else [None]

        generation_links: list[str] = []
        seen_links: set = set()
        for screen_size in sizes_to_search:
            search_url = self._build_search_url(screen_size)
            html = self._fetch_with_fallback(search_url, label=f"search page ({search_url})")
            if not html:
                continue

            soup = self.parse_html(html)
            for link in self._discover_generation_links(soup):
                if link not in seen_links:
                    seen_links.add(link)
                    generation_links.append(link)

        if not generation_links:
            print("  [Back Market] No product-page links discovered on search page(s)")
            return found

        # Bound how many product pages we fetch this run (see
        # MAX_DETAIL_PAGES docstring for why).
        generation_links = generation_links[: self.MAX_DETAIL_PAGES]

        # ── Step 2: fetch each product page and parse real listings ─
        max_results = self.config.search.results_per_size
        for link in generation_links:
            if len(found) >= max_results:
                break

            html = self._fetch_with_fallback(link, label=link)
            if not html:
                continue

            for offer in self._extract_variant_offers(html):
                if len(found) >= max_results:
                    break
                try:
                    listing = self._offer_to_listing(offer)
                except Exception:
                    # Skip individual offer parse errors -- don't fail the whole page.
                    continue
                if not listing or listing.listing_id in found_ids:
                    continue
                if self.passes_filters(listing):
                    found.append(listing)
                    found_ids.add(listing.listing_id)

        print(f"  [Back Market] Found {len(found)} matching listings")
        return found
