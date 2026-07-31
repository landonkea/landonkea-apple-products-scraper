# ─────────────────────────────────────────────────────────────────────
# Swappa scraper — fetches MacBook listings from swappa.com
# ─────────────────────────────────────────────────────────────────────
# Swappa is a peer-to-peer marketplace for used electronics.
# Unlike eBay, every listing is manually approved by Swappa staff,
# so listings are generally higher quality and more trustworthy.
#
# HOW THE SWAPPA API (WEBSITE) WORKS:
#   1. Start at a product page (e.g. /buy/macbooks/macbook-pro)
#      which shows product variants (e.g. "MacBook Pro 14" M3 2023").
#   2. Each variant has a SKU slug. Clicking it goes to a listings page
#      at /listings/{slug} showing all active listings for that variant.
#   3. Parse each listing card for price, specs, condition, etc.
#
# RATE LIMITING:
#   Swappa is fairly lenient. We add small delays between requests
#   via the base scraper's rate_limiter.
# ─────────────────────────────────────────────────────────────────────

import re
from typing import Optional

from scrapers.base import BaseScraper, ScrapedListing
from config import Config


class SwappaScraper(BaseScraper):
    """
    Scraper for Swappa marketplace listings.

    STRATEGY:
    - Fetch the product page to discover available model variants (slugs).
    - Fetch each variant's listing page to get individual listings.
    - Parse each listing for price, specs (RAM, storage, chip), and condition.

    WHY A TWO-STEP PROCESS:
    Swappa organizes listings by model variant, not by search query.
    You can't search "MacBook Pro" and get all listings — you must
    pick a specific variant first (e.g. "MacBook Pro 14\" M3 Pro 2023").
    This scraper automates that by scraping the product page for slugs.
    """

    # Base URL for all Swappa requests.
    BASE_URL = "https://swappa.com"

    def __init__(self, config: Config):
        """
        Initialize the Swappa scraper.

        Args:
            config: Global configuration object containing search settings
                    (product_name, screen_sizes, price limits, etc.)
        """
        # Call the parent BaseScraper constructor to set up rate limiting,
        # user-agent rotation, and shared parser utilities.
        super().__init__(config)
        # Source name used for deduplication across scrapers.
        self.source_name = "swappa"
        # Screen sizes the user wants to filter by (e.g. [14, 16]).
        self.target_screens = config.search.screen_sizes

    def _build_search_url(self, screen_size: Optional[int] = None) -> str:
        """
        Build the Swappa product page URL for the configured device.

        Swappa organizes products by category and slug.
        For example: /buy/macbooks/macbook-pro for MacBook Pro.

        Args:
            screen_size: Optional screen size filter (e.g. 14 for 14-inch).
                         If provided, we still use the same product page
                         but filter results during parsing.

        Returns:
            Full URL to the Swappa product listing page, sorted by price ascending.
        """
        if screen_size:
            # Screen size provided — build a product page URL for MacBook Pro.
            return f"{self.BASE_URL}/buy/macbooks/macbook-pro?sort=price_asc"

        product = self.config.search.product_name
        if "iphone" in product.lower():
            # Swappa has no per-model iPhone page (e.g. "iphone-17-pro-max"
            # 404s) — only the category root works. We rely on
            # passes_filters()'s model_keywords check to narrow results
            # down to the generations we actually want.
            return f"{self.BASE_URL}/buy/iphones?sort=price_asc"

        # No screen size, not an iPhone — determine category from config.
        slug = product.lower().replace(" ", "-")
        return f"{self.BASE_URL}/buy/{slug}/{slug}?sort=price_asc"

    def _discover_variant_slugs(self, soup) -> list[str]:
        """
        Find every model-variant SKU slug on a Swappa product page.

        WHAT: Scans the product page's variant cards (e.g. "MacBook
        Pro 14\" M3 2023") and pulls out each one's SKU slug, which is
        the identifier Swappa uses in its `/listings/{slug}` URLs.

        HOW: Each variant is rendered as a `div.card.card_product`.
        The slug normally lives in a `meta[itemprop="sku"]` tag inside
        the card; if that's missing, we fall back to parsing it out of
        the card's own link href. Cards are also filtered down to the
        screen sizes the user configured, if any, by checking whether
        the size appears in the card's title text.

        WHY A SEPARATE STEP: Swappa has no single search endpoint that
        returns all listings for a product — you must first discover
        which variant pages exist before you can fetch any listings.
        Isolating that discovery here keeps it independently testable
        and readable, separate from the per-variant fetch/parse step.

        Args:
            soup: Parsed BeautifulSoup of the product page HTML.

        Returns:
            A list of SKU slug strings, one per matching variant.
        """
        slugs: list[str] = []
        for card in soup.select("div.card.card_product"):
            # Each variant card has a title element with the model name.
            title_el = card.select_one(".card-title.title")
            if not title_el:
                # Skip cards without titles (shouldn't happen, but be safe).
                continue
            title = title_el.get_text(strip=True)

            # If the user specified screen sizes, filter variant cards by size.
            # We check if any target screen size string appears in the title.
            if self.target_screens and not any(str(size) in title for size in self.target_screens):
                continue

            # Extract the SKU slug from the variant card's meta tag.
            sku_el = card.select_one('meta[itemprop="sku"]')
            slug = sku_el.get("content", "") if sku_el else ""
            if not slug:
                # Fallback: extract slug from the card's link URL.
                link = card.select_one("a")
                if link and link.get("href", "").startswith("/listings/"):
                    slug = link["href"].replace("/listings/", "")
            if slug:
                slugs.append(slug)

        return slugs

    def _fetch_listings_for_slug(self, slug: str) -> list[dict]:
        """
        Fetch and parse all listing cards for a single variant slug.

        WHAT: Fetches the `/listings/{slug}` page for one model variant
        and parses every listing card on it into a raw listing dict.

        WHY PER-SLUG: Swappa exposes listings per variant, not via a
        combined search, so each slug discovered on the product page
        needs its own fetch. Isolating this per-slug logic keeps the
        network call and its error handling independent of the
        discovery step and easy to reason about (or retry) on its own.

        Args:
            slug: A Swappa SKU slug, e.g. "macbook-pro-14-m3-2023-16gb".

        Returns:
            A list of raw listing dicts parsed from that variant's
            listings page. Returns an empty list if the page fetch
            fails (the error is logged but not raised, so other
            variants can still be processed).
        """
        listings_url = f"{self.BASE_URL}/listings/{slug}"
        try:
            # Fetch the variant listing page.
            listings_html = self.fetch_page(listings_url)
            listings_soup = self.parse_html(listings_html)
            # Find and parse all listing cards on this variant page.
            listings = []
            for card in listings_soup.select("div.card.xui_card.xui_card_listing"):
                listing = self._parse_listing(card)
                if listing:
                    listings.append(listing)
            return listings
        except Exception as e:
            # Log the error but let the caller continue with other variants.
            print(f"  [Swappa] Error fetching listings for {slug}: {e}")
            return []

    def _fetch_listings_json(self, search_url: str) -> list[dict]:
        """
        Fetch all active listings for a product by scraping variant pages.

        HOW IT WORKS:
        1. Fetch the product page (e.g. /buy/macbooks/macbook-pro).
        2. Discover all model-variant SKU slugs via _discover_variant_slugs().
        3. Fetch and parse each variant's listing page via
           _fetch_listings_for_slug().
        4. Concatenate the results from every variant.

        WHY SPLIT THIS WAY: Discovering slugs and fetching a variant's
        listings are conceptually separate operations (one parses the
        product page, the other hits a different URL per variant), so
        each lives in its own single-purpose, independently readable
        method.

        Args:
            search_url: The Swappa product page URL to start from.

        Returns:
            List of raw listing dicts with keys:
            title, price, url, condition, listing_id, location,
            ram_gb, storage_gb, chip
        """
        # Fetch the product page HTML.
        html = self.fetch_page(search_url)
        # Parse HTML into BeautifulSoup for CSS selector queries.
        soup = self.parse_html(html)

        # Step 1: Find all model-variant SKU slugs on the product page.
        slugs = self._discover_variant_slugs(soup)

        # Step 2: Fetch each variant's listing page and parse individual listings.
        all_listings: list[dict] = []
        for slug in slugs:
            all_listings.extend(self._fetch_listings_for_slug(slug))

        return all_listings

    def _parse_listing(self, card) -> Optional[dict]:
        """
        Extract listing data from a single Swappa listing card element.

        Each listing card (div.card.xui_card.xui_card_listing) contains:
          - An image with alt text = the listing title.
          - A price span with itemprop="price".
          - A link to the full listing page.
          - Spec attributes (condition, storage, RAM, chip).

        Args:
            card: A BeautifulSoup element representing a listing card.

        Returns:
            Dictionary with parsed listing data, or None if parsing fails.
        """
        # Extract the listing title from the image alt attribute.
        img = card.select_one("img[alt]")
        title = img.get("alt", "") if img else ""
        if not title:
            # Fallback: try the headline div.
            title_el = card.select_one("div.headline")
            title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            # Can't parse a listing without a title.
            return None

        # Extract the price from the price span.
        price_el = card.select_one('div.price span[itemprop="price"]')
        if not price_el:
            return None
        price_text = price_el.get_text(strip=True).replace("$", "").replace(",", "")
        try:
            price = float(price_text)
        except ValueError:
            return None

        # Extract the listing URL from the price section's anchor tag.
        link_el = card.select_one("div.price a")
        url = link_el.get("href", "") if link_el else ""
        if url and not url.startswith("http"):
            # Prepend the base URL for relative links.
            url = f"{self.BASE_URL}{url}"

        # Extract the listing ID (unique identifier for deduplication).
        id_el = card.select_one("span.code.ms-2")
        listing_id = id_el.get_text(strip=True) if id_el else ""
        if not listing_id:
            # Fallback: extract from the URL path.
            m = re.search(r'/listing/view/([A-Z0-9]+)', url)
            if m:
                listing_id = m.group(1)

        # Extract the seller's location (city/state).
        location_el = card.select_one("div.ships_from")
        location = location_el.get_text(strip=True) if location_el else None

        # Extract specification attributes (condition, storage, RAM, chip).
        # These appear as span.attr elements inside div.attrs.
        attr_els = card.select("div.attrs span.attr")
        attrs = [a.get_text(strip=True) for a in attr_els] if attr_els else []

        # First attribute is usually the condition (e.g. "Good", "Mint").
        condition = attrs[0] if len(attrs) > 0 else None

        # Remaining attributes depend on the product type.
        # For MacBooks: [1] = storage, [2] = RAM, [3] = chip.
        raw_storage = attrs[1] if len(attrs) > 1 else ""
        raw_ram = attrs[2] if len(attrs) > 2 else ""
        raw_chip = attrs[3] if len(attrs) > 3 else ""

        # Parse storage (e.g. "512GB" or "1TB") into GB integer.
        storage_gb = None
        if raw_storage:
            m = re.search(r'(\d+)\s*(?:GB|TB)', raw_storage)
            if m:
                val = int(m.group(1))
                storage_gb = val * 1024 if "TB" in raw_storage.upper() else val

        # Parse RAM (e.g. "16GB") into GB integer.
        ram_gb = None
        if raw_ram:
            m = re.search(r'(\d+)\s*GB', raw_ram)
            if m:
                ram_gb = int(m.group(1))

        # Parse chip (e.g. "Apple M3 Pro") - strip the "Apple" prefix.
        chip = None
        if raw_chip:
            chip = raw_chip.replace("Apple ", "").strip()

        return {
            "title": title,
            "price": price,
            "url": url,
            "condition": condition,
            "listing_id": listing_id,
            "location": location,
            "ram_gb": ram_gb,
            "storage_gb": storage_gb,
            "chip": chip,
        }

    def _parse_item(self, item: dict) -> Optional[ScrapedListing]:
        """
        Convert a raw listing dict into a ScrapedListing dataclass.

        This method:
        1. Extracts fields from the raw dict.
        2. Falls back to extracting specs from the title string for any
           fields not directly parsed from the listing card.
        3. Creates a typed ScrapedListing object for the database.

        Args:
            item: Raw listing dict from _parse_listing().

        Returns:
            A ScrapedListing dataclass instance, or None if invalid.
        """
        title = item.get("title", "")
        if not title:
            return None

        price = item["price"]
        url = item.get("url", "")
        condition = item.get("condition")
        # Generate a unique listing ID, falling back to title hash.
        listing_id = item.get("listing_id", str(hash(title)))
        location = item.get("location")

        # Use explicitly parsed specs if available, otherwise extract from title.
        specs = self.parse_common_specs(title)
        ram = item.get("ram_gb") or specs["ram_gb"]
        storage = item.get("storage_gb") or specs["storage_gb"]
        screen = specs["screen_size"]
        chip = item.get("chip") or specs["chip"]
        cpu_cores = specs["cpu_cores"]
        gpu_cores = specs["gpu_cores"]

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
            location=location,
            cpu_cores=cpu_cores,
            gpu_cores=gpu_cores,
        )

    def scrape(self) -> list[ScrapedListing]:
        """
        Main entry point: fetch and parse all Swappa listings.

        This method is called by the orchestrator (main.py) for each scraper.
        It follows the same pattern as all other scrapers:
        1. Build search URLs for each screen size.
        2. Fetch and parse raw listings.
        3. Convert to ScrapedListing objects.
        4. Filter by price, condition, and other criteria.
        5. Deduplicate by listing_id.
        6. Return the final list.

        Returns:
            List of ScrapedListing objects matching the search criteria.
        """
        found: list[ScrapedListing] = []
        found_ids: set = set()

        # Determine which screen sizes to search.
        screen_sizes = self.config.search.screen_sizes
        sizes_to_search = screen_sizes if screen_sizes else [None]
        # Build the search URL for the first (or only) screen size.
        search_url = self._build_search_url(sizes_to_search[0])

        try:
            # Fetch all raw listings from the product and variant pages.
            raw_listings = self._fetch_listings_json(search_url)
        except Exception as e:
            print(f"  [Swappa] Error fetching listings: {e}")
            return found

        # Convert each raw listing to a ScrapedListing and apply filters.
        for item in raw_listings:
            try:
                listing = self._parse_item(item)
                if listing and listing.listing_id not in found_ids:
                    # Apply user-configured filters (price, condition, etc.).
                    if self.passes_filters(listing):
                        found.append(listing)
                        found_ids.add(listing.listing_id)
            except Exception:
                # Skip individual listing parse errors — don't fail the whole batch.
                continue

        print(f"  [Swappa] Found {len(found)} matching listings")
        return found
