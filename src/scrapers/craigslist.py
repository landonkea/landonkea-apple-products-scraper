# ───────────────────────────────────────────────────────────────────
# Craigslist scraper — fetches listings from craigslist.org
# ───────────────────────────────────────────────────────────────────
# Craigslist is local classifieds, organized by CITY/METRO REGION
# (not by state) — each region used to live on its own subdomain
# (e.g. phoenix.craigslist.org) and still does for the *listing detail*
# page, but search itself has moved to a consolidated host. See the
# LIVE-TESTING FINDINGS below. The region this scraper searches is a
# config value (config.yaml sites.craigslist.region, default
# "phoenix" — the largest Arizona metro), NOT hardcoded, so switching
# to a different city/state later is a one-line config.yaml edit, no
# code changes. See config.py's SiteConfig.region field.
#
# LIVE-TESTING FINDINGS (this is what the code below is built on —
# do not "fix" this scraper based on assumptions without re-checking
# these against the real site first. Checked 2026-07-31):
#
#   1. OLD per-city subdomain search URLs now 301-redirect to a NEW
#      consolidated host. Confirmed via `curl -sIL`:
#        https://phoenix.craigslist.org/search/sya?query=macbook+pro
#          -> 301 -> https://www.craigslist.org/search/area/phoenix
#                     ?cat=sya&query=macbook%20pro
#      Both the old subdomain URL (followed) and the new consolidated
#      URL return HTTP 200. The new URL shape is:
#        https://www.craigslist.org/search/area/{region}?cat={cat}&query={query}
#      `{region}` is the metro slug (e.g. "phoenix", "tucson" — both
#      confirmed live, tucson returning fewer results as expected for
#      a smaller metro). This scraper builds that URL directly rather
#      than relying on the old subdomain, since the subdomain form
#      just costs an extra redirect hop for the same result.
#
#   2. CATEGORY CODE: `cat=sss` ("for sale - all") was used, not
#      `cat=sya` (electronics only). Both were tested live and both
#      work with zero JS/bot-block issues, but `sya` cut phoenix's
#      130-result "macbook pro" query down to 55 by filtering out
#      genuinely-relevant results filed under other categories (e.g.
#      a listing categorized under general "for sale" rather than
#      "electronics"). Since Craigslist is a general classifieds site
#      (like eBay/Swappa — see applicable_product_types=None in
#      config.py, applies to every product type, not just
#      electronics), `sss` is the correct broad default so a future
#      non-electronics search (e.g. apparel) isn't silently scoped to
#      an electronics-only category.
#
#   3. IS IT JS-RENDERED? Mixed answer, but the practical answer for
#      scraping is NO. The live page (`view-source` on the fetched
#      HTML) ships a `<body class="no-js">` with a loading "curtain"
#      overlay that a real browser's JS removes before rendering
#      results client-side. BUT — critically — the *same* initial
#      HTML response also embeds a fully-populated, real
#      `<ol class="cl-static-search-results">` fallback list (only
#      CSS-hidden via `.cl-static-search-results { display:none }`,
#      shown when `.no-js` is present, i.e. exactly what a plain
#      `requests.get()` receives). This is a progressive-enhancement
#      pattern, not a bot wall: `fetch_page()` (plain HTTP, no
#      Playwright) gets the complete, real listing data on the first
#      response. Confirmed via `curl` with a plain desktop UA, zero
#      cookies/session warm-up: HTTP 200, and
#      `grep -c 'cl-static-search-result'` on the raw response found
#      130 real listings for a "macbook pro" / phoenix / cat=sss
#      query. There is ALSO a `<script type="application/ld+json"
#      id="ld_searchpage_results">` JSON-LD block with the same
#      result set in a different shape (price/name/geo-coordinates,
#      but no listing URL or location city text) — considered as an
#      alternative data source, but the static `<li>` HTML has
#      everything JSON-LD lacks (URL, listing ID, city name) plus
#      everything JSON-LD has (title, price), so this scraper parses
#      the `<li class="cl-static-search-result">` list, not the
#      JSON-LD block.
#
#   4. LISTING CARD STRUCTURE (from live HTML, not assumed):
#        <li class="cl-static-search-result" title="<full title>">
#          <a href="https://www.craigslist.org/view/d/<slug>/<id>">
#            <div class="title"><full title></div>
#            <div class="details">
#              <div class="price">$1,700</div>
#              <div class="location">Phoenix</div>
#            </div>
#          </a>
#        </li>
#      The listing ID is the last path segment of the URL (e.g.
#      "c9yAuUSPCiAE7juezJsoux"). `location` is a bare city name with
#      no state suffix (e.g. "Chandler", "Tempe") — Craigslist does
#      not expose a separate state field on the search results page,
#      so `listing.location` is stored as-is rather than guessing/
#      appending a state that isn't actually on the page.
#
#   5. NO FORMAL "CONDITION" FIELD. Unlike eBay/Swappa/BackMarket,
#      Craigslist search results carry no structured condition badge
#      at all — sellers sometimes mention "like new" or "used" in the
#      free-text title, but there's no separate field to extract.
#      Documented honestly: `condition` is always `None` for Craigslist
#      listings. `passes_filters()` / `is_relevant()` both already
#      handle `condition=None` safely (they do `condition_lower =
#      (condition or "").lower()` — see product_types/electronics.py),
#      so this doesn't break any downstream filtering.
#
#   6. SERVER-SIDE PRICE FILTER WORKS: appending `&max_price=500` to
#      the search URL was tested live and genuinely narrowed phoenix's
#      130-result query down to 77, all priced <= 500 (confirmed by
#      grepping the returned prices). Used here to keep the fetched
#      page smaller and avoid wasting requests on listings that would
#      just get filtered out by passes_filters() anyway.
#
#   7. PAGINATION: not implemented. The single static-fallback page
#      already returned the *entire* matching result set (130 items
#      for a fairly common query) rather than a truncated first page —
#      appending `&s=120` (Craigslist's classic pagination offset
#      param) actually 301-redirected back to a bare URL rather than
#      returning a second page, suggesting the new consolidated search
#      no longer paginates the static-fallback content the old way.
#      If a search someday returns more than `results_per_size` real
#      matches, this scraper simply stops early once its cap is hit
#      (same pattern as every other scraper here) rather than guessing
#      at an unverified pagination parameter.
#
#   8. ROBOTS.TXT / BOT BLOCKS: `https://www.craigslist.org/robots.txt`
#      disallows only `/reply`, `/fb/`, `/suggest`, `/flag`, `/mf`,
#      `/mailflag`, `/eaf`, `/sitemap/` — none of which this scraper
#      touches. `/search/...` is not disallowed. No Cloudflare
#      challenge or captcha was encountered on any request made while
#      researching this scraper (all plain `curl`, no browser).
#
#   9. LEGAL / ToS NOTE (see also this scraper's config.yaml comment
#      and the PR/commit description): Craigslist's Terms of Use have
#      historically been stricter about automated access than most
#      other sites this project scrapes (it has litigated against
#      scrapers in the past, e.g. Craigslist v. 3Taps/PadMapper).
#      robots.txt does not disallow the search paths used here, and
#      this scraper follows the same low-volume, rate-limited,
#      personal-use pattern as every other scraper in this repo (see
#      BaseScraper.fetch_page's built-in delay/retry behavior) — but
#      this is a materially different risk profile than eBay/Swappa's
#      scraper-tolerant public APIs, and is called out explicitly here
#      rather than treated as equivalent-risk by default.
# ───────────────────────────────────────────────────────────────────

import re
from typing import Optional
from urllib.parse import quote

from scrapers.base import BaseScraper, ScrapedListing
from config import Config


class CraigslistScraper(BaseScraper):
    """
    Scraper for Craigslist (craigslist.org) local classifieds.

    Craigslist is a general classifieds site (like eBay/Swappa), not
    an electronics-only storefront — see applicable_product_types=None
    in config.yaml's craigslist entry — so it's searched for every
    product type, not just MacBook Pro / iPhone.

    The metro region searched (e.g. "phoenix") is config-driven via
    config.sites.craigslist.region, defaulting to "phoenix" if unset.
    See the module docstring's LIVE-TESTING FINDINGS for exactly how
    the search URL, listing HTML structure, and filters were verified.
    """

    BASE_URL = "https://www.craigslist.org"
    # "for sale - all" — the broad category, not electronics-only
    # ("sya"). See LIVE-TESTING FINDINGS point 2 for why.
    CATEGORY = "sss"
    # Fallback if config.yaml's sites.craigslist.region is unset —
    # Phoenix is the largest Arizona metro (this project's default
    # search area).
    DEFAULT_REGION = "phoenix"

    def __init__(self, config: Config):
        super().__init__(config)
        self.source_name = "craigslist"

    @property
    def region(self) -> str:
        """
        The Craigslist metro region slug to search (e.g. "phoenix",
        "tucson"). Config-driven — see config.py's SiteConfig.region
        and config.yaml's sites.craigslist.region — so switching
        metros never requires a code change.
        """
        site_config = self.config.sites.craigslist
        return site_config.region or self.DEFAULT_REGION

    def _build_search_url(self) -> str:
        """
        Build the Craigslist search URL for the active search and
        configured region.

        Uses the consolidated `/search/area/{region}` URL shape (see
        LIVE-TESTING FINDINGS point 1 — the old per-city subdomain
        form just 301-redirects to this), the broad "sss" category
        (point 2), and a server-side `max_price` filter (point 6) to
        avoid wasting a request on listings passes_filters() would
        reject anyway.

        Returns:
            A full Craigslist search URL.
        """
        query = quote(self.config.search.product_name)
        max_price = int(self.config.price.absolute_max_usd)
        return (
            f"{self.BASE_URL}/search/area/{self.region}"
            f"?cat={self.CATEGORY}&query={query}&max_price={max_price}"
        )

    def _parse_price(self, text: str) -> Optional[float]:
        """
        Parse a Craigslist price string (e.g. "$1,700") into a float.

        Args:
            text: The raw text of a `div.price` element.

        Returns:
            The price as a float, or None if no digits were found.
        """
        cleaned = text.replace("$", "").replace(",", "").strip()
        match = re.search(r"(\d+(?:\.\d+)?)", cleaned)
        if match:
            return float(match.group(1))
        return None

    def _get_listing_id(self, url: str) -> str:
        """
        Extract a unique listing ID from a Craigslist listing URL.

        Craigslist listing URLs look like
        ".../view/d/<slug>/<id>" — the last path segment is a stable,
        unique ID for the posting. Falls back to a hash of the URL if
        the shape doesn't match (defensive, not seen live).

        Args:
            url: The listing's full URL.

        Returns:
            A unique string identifier for this listing, prefixed
            "craigslist-" so it can never collide with another
            source's listing_id in the shared database.
        """
        segment = url.rstrip("/").rsplit("/", 1)[-1]
        if segment:
            return f"craigslist-{segment}"
        return f"craigslist-url_{hash(url)}"

    def _parse_single_item(self, item) -> Optional[ScrapedListing]:
        """
        Parse a single Craigslist search result `<li>` into a
        ScrapedListing.

        Args:
            item: BeautifulSoup element for one
                `li.cl-static-search-result`.

        Returns:
            A ScrapedListing, or None if required fields are missing.
        """
        # The full title is also on the <li title="..."> attribute,
        # but the div.title text is the more direct/reliable source —
        # both were confirmed identical live.
        title_el = item.select_one("div.title")
        title = title_el.get_text(strip=True) if title_el else ""
        if not title:
            return None

        link_el = item.select_one("a")
        url = link_el.get("href", "") if link_el else ""
        if not url:
            return None

        price_el = item.select_one("div.price")
        if not price_el:
            return None
        price = self._parse_price(price_el.get_text())
        if price is None:
            return None

        location_el = item.select_one("div.location")
        location = location_el.get_text(strip=True) if location_el else None

        listing_id = self._get_listing_id(url)
        specs = self.parse_common_specs(title)

        return ScrapedListing(
            source=self.source_name,
            listing_id=listing_id,
            title=title,
            price_usd=price,
            url=url,
            # Craigslist has no structured condition field — see
            # LIVE-TESTING FINDINGS point 5. Always None, honestly.
            condition=None,
            ram_gb=specs["ram_gb"],
            storage_gb=specs["storage_gb"],
            screen_size=specs["screen_size"],
            chip=specs["chip"],
            location=location,
            cpu_cores=specs["cpu_cores"],
            gpu_cores=specs["gpu_cores"],
        )

    def _fetch_cards(self) -> list:
        """
        Fetch the Craigslist search results page and return its
        listing cards (`li.cl-static-search-result` elements).

        HOW: A single request gets the entire result set — see
        LIVE-TESTING FINDINGS point 7 for why this scraper doesn't
        paginate. Fetch/parse failures return an empty list rather
        than raising, matching every other scraper's fetch-helper
        pattern here (e.g. newegg.py's _fetch_page_cards()).

        Returns:
            A list of BeautifulSoup `li.cl-static-search-result`
            elements. Empty if the fetch failed or there are no
            results.
        """
        url = self._build_search_url()
        try:
            html = self.fetch_page(url)
        except Exception as e:
            print(f"  [Craigslist] Failed to fetch search results: {e}")
            return []

        soup = self.parse_html(html)
        return soup.select("li.cl-static-search-result")

    def scrape(self) -> list[ScrapedListing]:
        """
        Main entry point: fetch and parse Craigslist listings for the
        active search and configured region.

        1. Fetch the search results page (single request — see
           LIVE-TESTING FINDINGS point 7).
        2. Parse each listing card, apply passes_filters().
        3. Deduplicate by listing_id, stopping once results_per_size
           matches are collected.

        Returns:
            List of ScrapedListing objects matching our filters.
        """
        found: list[ScrapedListing] = []
        found_ids: set = set()
        max_results = self.config.search.results_per_size

        cards = self._fetch_cards()

        for item in cards:
            if len(found) >= max_results:
                break
            try:
                listing = self._parse_single_item(item)
                if listing and listing.listing_id not in found_ids:
                    if self.passes_filters(listing):
                        found.append(listing)
                        found_ids.add(listing.listing_id)
            except Exception:
                # Skip individual listing parse errors — don't fail
                # the whole batch.
                continue

        print(f"  [Craigslist] Found {len(found)} matching listings (region={self.region})")
        return found
