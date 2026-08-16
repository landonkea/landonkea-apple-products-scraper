# ─────────────────────────────────────────────────────────────────────
# Pinkbike BuySell scraper, fetches used e-bike listings
# ─────────────────────────────────────────────────────────────────────
# Pinkbike is a mountain-bike-focused site whose BuySell marketplace
# also carries a dedicated e-bike section, useful here because it's
# bike-specific (better signal-to-noise than a general classifieds
# site) and reaches sellers a general marketplace search wouldn't.
# `applicable_product_types: ["ebike"]` in config.yaml (see SiteConfig
# in config.py) means this scraper is automatically skipped for every
# non-ebike search, the same way apple_refurb/bestbuy/newegg/gazelle
# are skipped for a non-electronics search.
#
# LIVE-TESTING FINDINGS (checked 2026-08-14, do not "fix" this scraper
# based on assumptions without re-checking these against the real site
# first):
#
#   1. PLAIN HTTP IS BLOCKED: `curl` against
#      https://www.pinkbike.com/buysell/list/?category=63 returns
#      HTTP 403 with Cloudflare bot-management cookies (`__cf_bm`) in
#      the response, confirmed via `curl -sIL`. Every fetch here goes
#      through Playwright (fetch_with_playwright()-style), not
#      fetch_page().
#
#   2. PLAIN PLAYWRIGHT IS ENOUGH: unlike Back Market
#      (scrapers/backmarket.py), which needs the playwright_stealth
#      plugin to get past Cloudflare, a live test found plain headless
#      Chromium (with `--disable-blink-features=AutomationControlled`,
#      no stealth plugin) gets a real HTTP 200 with the full, real
#      listing HTML on the first navigation, no challenge/"Just a
#      moment" page. So this scraper uses a lighter fetch method than
#      Back Market's, no playwright_stealth dependency needed.
#
#   3. CATEGORY IDS (from the buysell homepage's category dropdown,
#      confirmed live): "Ebikes - Urban/Commuter" is category 63.
#      Pinkbike also has "Ebikes - Mountain" (74), "Ebikes - Road"
#      (64), and "Ebike - Parts" (65), category 63 is the only one
#      this scraper searches, a folding commuter bike belongs in
#      Urban/Commuter, and pulling in Mountain/Road would mostly add
#      irrelevant full-suspension trail bikes and drop-bar road bikes
#      to sift through.
#
#   4. REGION FILTER: `&region=3` scopes results to "Canada/USA" (the
#      site's own regional grouping, confirmed live via the page's
#      region-chooser filter, which also offered Europe/South America/
#      Australia-NZ). This is already the DEFAULT region even without
#      the param (checked live: the unfiltered category=63 page and
#      the explicit region=3 page returned the same result set), but
#      it's included explicitly in the URL so a defaulting change on
#      Pinkbike's end doesn't silently start returning results outside
#      North America.
#
#   5. LISTING CARD STRUCTURE (from live HTML, not assumed): each
#      listing is a `<div class="bsitem ">` or `<div class="bsitem
#      boosted">` (a paid-promotion variant, same schema, both matched
#      by the CSS class selector "div.bsitem"), containing:
#        - `.bsitem-title a`, the title text and the listing URL
#          (`https://www.pinkbike.com/buysell/<id>/`), the numeric id
#          is the last path segment.
#        - `.itemdetail` divs with a `<b>Label :</b> Value` shape for
#          Category / Condition / Seller / Frame Size / Wheel Size,
#          used here to extract a real Condition field (Pinkbike has
#          one, unlike Craigslist).
#        - `.bsitem-price b`, price text like "$1900 USD" or "$4199
#          CAD", see finding 6 below for why the currency suffix
#          matters.
#        - a location line (city/province/country) in the same table,
#          following a small flag `<img>`, get_text() on that cell
#          naturally skips the image and returns just the text.
#
#   6. MIXED CURRENCY, NOT JUST MIXED LOCATION: even within the
#      Canada/USA region filter, prices are NOT all USD, a live sample
#      of 20 category-63 listings had both "$X USD" (US sellers) and
#      "$X CAD" (Canadian sellers) in the SAME result set, at face-
#      value numbers that are NOT interchangeable (1 CAD is roughly
#      0.70-0.75 USD). Rather than apply a currency conversion rate
#      that will drift out of date, this scraper only accepts listings
#      whose price explicitly states "USD", any other currency suffix
#      (CAD, EUR, GBP, ...) is skipped entirely, this also happens to
#      bias toward US-based sellers, which fits the rider's Phoenix,
#      AZ + "prioritize what's realistically shippable within the US"
#      framing.
#
#   7. PAGINATION: `&page=N` (1-indexed... actually 0-indexed for the
#      first page per the live pagination links, which listed the
#      current page's own link as `page=1` while sitting on what's
#      displayed as results 1-20, so this scraper treats the first
#      fetch as page=1 and increments from there, matching the site's
#      own link values rather than assuming a 0-indexed scheme). 20
#      listings per page, a live category-63 fetch showed 15 total
#      pages (~300 listings region-wide). This scraper caps how many
#      pages it fetches per run (MAX_PAGES below), matching Back
#      Market's MAX_DETAIL_PAGES rationale, each page fetch launches a
#      fresh headless-Chromium session, so following all 15 pages
#      unconditionally would make a single scrape take several minutes
#      for one marketplace.
#
#   8. SORT ORDER: `&sort=price-up` (confirmed as a real, working sort
#      link on the live page) sorts ascending by price, same
#      "cheapest first" bias as eBay's `_sop=15` here, useful since
#      results_per_size caps how many listings this scraper keeps.
# ─────────────────────────────────────────────────────────────────────

import re
from typing import Optional

from scrapers.base import BaseScraper, ScrapedListing
from config import Config


class PinkbikeScraper(BaseScraper):
    """
    Scraper for Pinkbike's BuySell marketplace, "Ebikes -
    Urban/Commuter" category only (category=63, see module docstring
    finding 3). Bike-specific, applicable_product_types: ["ebike"] in
    config.yaml means this never runs for an electronics/apparel
    search.
    """

    CATEGORY_URBAN_COMMUTER = 63
    REGION_CANADA_USA = 3
    # Bounds how many result pages this scraper fetches per run (each
    # page fetch launches a fresh headless-Chromium session, see
    # module docstring finding 7). A breadth cap, not a spec filter,
    # passes_filters() still does the real filtering on whatever pages
    # do get fetched.
    MAX_PAGES = 3

    def __init__(self, config: Config):
        super().__init__(config)
        self.source_name = "pinkbike"

    def _build_search_url(self, page: int) -> str:
        """
        Build the Pinkbike BuySell search URL for one result page.

        See module docstring findings 3/4/7/8 for why category=63,
        region=3, page=N, and sort=price-up are exactly what they are,
        each was verified against the live site, not assumed.
        """
        return (
            "https://www.pinkbike.com/buysell/list/"
            f"?category={self.CATEGORY_URBAN_COMMUTER}"
            f"&region={self.REGION_CANADA_USA}"
            f"&sort=price-up"
            f"&page={page}"
        )

    def _fetch_page_html(self, url: str) -> Optional[str]:
        """
        Fetch one Pinkbike BuySell search page with Playwright.

        WHY A DEDICATED METHOD (not BaseScraper.fetch_with_playwright()
        as-is): the live test that confirmed this site is reachable
        without playwright_stealth (module docstring finding 2) used
        `--disable-blink-features=AutomationControlled` and a 5-second
        post-navigation wait, one flag and one timeout value
        BaseScraper's generic fetch_with_playwright() doesn't set.
        Written here explicitly so this scraper only ever relies on
        the exact fetch behavior that was actually verified live
        against this specific site, not an assumption that the base
        class's generic settings would behave the same way.

        Args:
            url: The Pinkbike search URL to fetch.

        Returns:
            The rendered page HTML, or None if every fetch attempt
            failed.
        """
        try:
            from playwright.sync_api import sync_playwright

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
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
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(5000)
                html = page.content()
                browser.close()
                return html
        except Exception as e:
            print(f"  [Pinkbike] Playwright fetch failed for {url}: {e}, "
                  f"trying plain request (expected to also fail, see "
                  f"module docstring finding 1)...")
            try:
                return self.fetch_page(url)
            except Exception as e2:
                print(f"  [Pinkbike] Plain request also failed: {e2}")
                return None

    def _parse_price_usd(self, text: str) -> Optional[float]:
        """
        Parse a Pinkbike price string, e.g. "$1900 USD", into a float,
        ONLY when the currency is explicitly USD (see module docstring
        finding 6, CAD/EUR/GBP listings are common in the same result
        set and are not interchangeable at face value).

        Args:
            text: The raw text of a `.bsitem-price b` element.

        Returns:
            The price as a float, or None if it's missing, unparseable,
            or not stated in USD.
        """
        match = re.search(r'\$?\s*([\d,]+(?:\.\d{1,2})?)\s*(USD|CAD|EUR|GBP|AUD)\b', text, re.IGNORECASE)
        if not match:
            return None
        if match.group(2).upper() != "USD":
            return None
        return float(match.group(1).replace(",", ""))

    def _get_listing_id(self, url: str) -> str:
        """
        Extract a unique listing ID from a Pinkbike listing URL
        (".../buysell/<id>/"), prefixed "pinkbike-" so it can never
        collide with another source's listing_id in the shared
        database.
        """
        match = re.search(r'/buysell/(\d+)', url)
        if match:
            return f"pinkbike-{match.group(1)}"
        return f"pinkbike-url_{hash(url)}"

    def _extract_condition(self, item) -> Optional[str]:
        """
        Extract the "Condition : <value>" itemdetail field, see module
        docstring finding 5 for the `<b>Label :</b> Value` shape these
        are written in.
        """
        for detail in item.select("div.itemdetail"):
            text = detail.get_text(" ", strip=True)
            if text.lower().startswith("condition"):
                return text.split(":", 1)[-1].strip()
        return None

    def _parse_single_item(self, item) -> Optional[ScrapedListing]:
        """
        Parse a single Pinkbike BuySell listing card
        (`div.bsitem`/`div.bsitem.boosted`) into a ScrapedListing.

        Args:
            item: BeautifulSoup element for one listing card.

        Returns:
            A ScrapedListing, or None if required fields are missing
            or the price isn't stated in USD.
        """
        title_el = item.select_one("div.bsitem-title a")
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            return None

        url = title_el.get("href", "") if title_el else ""
        if not url:
            return None

        price_el = item.select_one("td.bsitem-price b")
        if not price_el:
            return None
        price = self._parse_price_usd(price_el.get_text())
        if price is None:
            return None

        # Location: the row right after the price row in
        # bsitem-details, holding a small flag <img> followed by the
        # location text -- get_text() naturally skips the <img>.
        location = None
        details_table = item.select_one("table.bsitem-details")
        if details_table:
            rows = details_table.select("tr")
            if len(rows) >= 2:
                location_text = rows[1].get_text(" ", strip=True)
                if location_text:
                    location = location_text

        condition = self._extract_condition(item)
        listing_id = self._get_listing_id(url)
        specs = self.parse_common_specs(title)

        return ScrapedListing(
            source=self.source_name,
            listing_id=listing_id,
            title=title,
            price_usd=price,
            url=url,
            condition=condition,
            ram_gb=specs["ram_gb"],
            storage_gb=specs["storage_gb"],
            screen_size=specs["screen_size"],
            chip=specs["chip"],
            location=location,
            cpu_cores=specs["cpu_cores"],
            gpu_cores=specs["gpu_cores"],
            brand=specs["brand"],
            wheel_size_in=specs["wheel_size_in"],
            fat_tire=specs["fat_tire"],
            step_through=specs["step_through"],
            folding=specs["folding"],
            battery_voltage=specs["battery_voltage"],
            battery_ah=specs["battery_ah"],
            battery_wh=specs["battery_wh"],
            motor_watts_nominal=specs["motor_watts_nominal"],
            motor_watts_peak=specs["motor_watts_peak"],
            weight_capacity_lb=specs["weight_capacity_lb"],
            brake_type=specs["brake_type"],
            suspension=specs["suspension"],
            ul_certified=specs["ul_certified"],
        )

    def scrape(self) -> list[ScrapedListing]:
        """
        Main entry point: fetch and parse Pinkbike BuySell "Ebikes -
        Urban/Commuter" listings, up to MAX_PAGES pages or
        results_per_size matches, whichever comes first.

        Returns:
            List of ScrapedListing objects matching our filters.
        """
        found: list[ScrapedListing] = []
        found_ids: set = set()
        max_results = self.config.search.results_per_size

        for page_num in range(1, self.MAX_PAGES + 1):
            if len(found) >= max_results:
                break

            url = self._build_search_url(page_num)
            html = self._fetch_page_html(url)
            if not html:
                continue

            soup = self.parse_html(html)
            cards = soup.select("div.bsitem")
            if not cards:
                # No more results (or the page structure changed) --
                # stop paginating rather than fetching empty pages.
                break

            page_count = 0
            for item in cards:
                if len(found) >= max_results:
                    break
                try:
                    listing = self._parse_single_item(item)
                    if listing and listing.listing_id not in found_ids:
                        if self.passes_filters(listing):
                            found.append(listing)
                            found_ids.add(listing.listing_id)
                            page_count += 1
                except Exception:
                    # Skip individual listing parse errors, don't
                    # fail the whole batch.
                    continue

            print(f"  [Pinkbike] page={page_num}: {page_count} matching listings")

        print(f"  [Pinkbike] Found {len(found)} matching listings total")
        return found
