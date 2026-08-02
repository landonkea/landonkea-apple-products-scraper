# ───────────────────────────────────────────────────────────────────
# Craigslist scraper — fetches listings from craigslist.org
# ───────────────────────────────────────────────────────────────────
# Craigslist is local classifieds, organized by CITY/METRO REGION
# (not by state) — each region used to live on its own subdomain
# (e.g. phoenix.craigslist.org) and still does for the *listing detail*
# page, but search itself has moved to a consolidated host. See the
# LIVE-TESTING FINDINGS below. The region(s) this scraper searches are
# a config value (config.yaml sites.craigslist.regions, a LIST — e.g.
# ["phoenix", "tucson", "losangeles"]), NOT hardcoded, so widening or
# narrowing coverage later is a config.yaml edit, no code changes. See
# config.py's SiteConfig.regions field.
#
# MULTI-STATE / MULTI-REGION COVERAGE (added 2026-08-02): a single
# Craigslist "region" is one metro, not a state — California alone
# has 20+ separate regions (losangeles, sfbay, sandiego, sacramento,
# etc). To cover multiple states, this scraper loops over EVERY slug
# in config.yaml's sites.craigslist.regions and aggregates results,
# reusing the same fetch_page() (which already rate-limits every
# request — see BaseScraper.fetch_page's 1.5-2.5s randomized delay
# and retry/backoff) so looping over many regions doesn't hammer
# Craigslist with rapid-fire requests. Cross-region (and cross-source)
# duplicate listings are handled downstream in main.py by
# source+listing_id, not here — this scraper does its own in-run
# de-dup by listing_id (same as before) but doesn't need to know or
# care whether the same listing could theoretically appear under two
# regions.
#
# A "search nearby areas" broadening feature (a checkbox/param on
# classic per-city Craigslist search pages) was investigated FIRST as
# a cheaper alternative to enumerating regions, and rejected — see
# LIVE-TESTING FINDINGS point 10 below for what was actually checked.
#
# LIVE-TESTING FINDINGS (this is what the code below is built on —
# do not "fix" this scraper based on assumptions without re-checking
# these against the real site first. Checked 2026-07-31, region-list
# behavior + slugs re-verified 2026-08-02):
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
#
#  10. "SEARCH NEARBY AREAS" DOES NOT EXIST ON THE CONSOLIDATED HOST
#      (checked 2026-08-02, before deciding to enumerate regions):
#      fetched a live phoenix search both with and without
#      `&searchNearby=1` appended
#      (https://www.craigslist.org/search/area/phoenix?cat=sss&query=
#      macbook+pro) — the param had NO effect on result count (111 vs
#      112, within normal listing churn between two live fetches, not
#      a meaningful broadening) and no listing outside the Phoenix
#      metro area appeared. Also grepped the full raw HTML response
#      for "nearby" (case-insensitive): zero matches — no checkbox,
#      no UI element, no JS variable referencing a nearby-areas
#      feature at all on this consolidated `/search/area/{region}`
#      host. (The classic per-subdomain craigslist.org UI reportedly
#      had this in the past, but it's gone from the current search
#      page.) Also tried an `areaID=1` param as a guess at a
#      multi-region combinator — no effect either. Conclusion: with no
#      working single-request broadening mechanism, enumerating actual
#      region slugs (see config.yaml sites.craigslist.regions) is the
#      only way to cover multiple states, so that's what this scraper
#      does — see the "MULTI-STATE / MULTI-REGION COVERAGE" note above
#      the LIVE-TESTING FINDINGS section.
#
#  11. REGION SLUGS VERIFIED LIVE (2026-08-02): every slug below was
#      curl-fetched against `https://www.craigslist.org/search/area/
#      {slug}?cat=sss&query=macbook+pro` and confirmed HTTP 200 with a
#      non-zero `cl-static-search-result` count (i.e. a real search
#      page, not an error page): phoenix (AZ, 112 results), tucson
#      (AZ, 14), albuquerque (NM, 13), santafe (NM, 11), losangeles
#      (CA, 264), sfbay (CA, 343), sandiego (CA, 70), sacramento (CA,
#      90), saltlakecity (UT, 6), provo (UT, 4), lasvegas (NV, 37),
#      reno (NV, 12), denver (CO, 35), cosprings (CO, 7), boulder (CO,
#      12). One guessed slug was WRONG and confirmed 404: Colorado
#      Springs is "cosprings", NOT "coloradosprings" — don't
#      reintroduce that typo.
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

    The metro region(s) searched (e.g. "phoenix", "tucson") are
    config-driven via config.sites.craigslist.regions (a list),
    defaulting to just Phoenix if unset. `scrape()` loops over every
    configured region, aggregating results, to cover multiple states
    in one run — see the module docstring's "MULTI-STATE / MULTI-
    REGION COVERAGE" note. See the module docstring's LIVE-TESTING
    FINDINGS for exactly how the search URL, listing HTML structure,
    and filters were verified.
    """

    BASE_URL = "https://www.craigslist.org"
    # "for sale - all" — the broad category, not electronics-only
    # ("sya"). See LIVE-TESTING FINDINGS point 2 for why.
    CATEGORY = "sss"
    # Fallback if config.yaml's sites.craigslist.regions is unset or
    # empty — Phoenix is the largest Arizona metro (this project's
    # original default search area).
    DEFAULT_REGIONS = ["phoenix"]

    def __init__(self, config: Config):
        super().__init__(config)
        self.source_name = "craigslist"

    @property
    def regions(self) -> list[str]:
        """
        The Craigslist metro region slugs to search (e.g. "phoenix",
        "tucson", "losangeles"). Config-driven — see config.py's
        SiteConfig.regions and config.yaml's sites.craigslist.regions
        — so widening/narrowing coverage never requires a code change.
        """
        site_config = self.config.sites.craigslist
        return list(site_config.regions) if site_config.regions else list(self.DEFAULT_REGIONS)

    def _build_search_url(self, region: str) -> str:
        """
        Build the Craigslist search URL for the active search and a
        given region.

        Uses the consolidated `/search/area/{region}` URL shape (see
        LIVE-TESTING FINDINGS point 1 — the old per-city subdomain
        form just 301-redirects to this), the broad "sss" category
        (point 2), and a server-side `max_price` filter (point 6) to
        avoid wasting a request on listings passes_filters() would
        reject anyway.

        Args:
            region: The Craigslist metro region slug to search.

        Returns:
            A full Craigslist search URL for that region.
        """
        query = quote(self.config.search.product_name)
        max_price = int(self.config.price.absolute_max_usd)
        return (
            f"{self.BASE_URL}/search/area/{region}"
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

    def _fetch_cards(self, region: str) -> list:
        """
        Fetch one region's Craigslist search results page and return
        its listing cards (`li.cl-static-search-result` elements).

        HOW: A single request per region gets that region's entire
        result set — see LIVE-TESTING FINDINGS point 7 for why this
        scraper doesn't paginate. Rate limiting between requests
        (including across regions in scrape()'s loop) is handled by
        fetch_page() itself (BaseScraper.fetch_page's randomized
        1.5-2.5s delay + retry/backoff), so callers don't need to add
        their own delay. Fetch/parse failures return an empty list
        rather than raising, matching every other scraper's fetch-
        helper pattern here (e.g. newegg.py's _fetch_page_cards()) —
        one bad region shouldn't abort the whole multi-region scrape.

        Args:
            region: The Craigslist metro region slug to fetch.

        Returns:
            A list of BeautifulSoup `li.cl-static-search-result`
            elements. Empty if the fetch failed or there are no
            results.
        """
        url = self._build_search_url(region)
        try:
            html = self.fetch_page(url)
        except Exception as e:
            print(f"  [Craigslist] Failed to fetch search results for region={region}: {e}")
            return []

        soup = self.parse_html(html)
        return soup.select("li.cl-static-search-result")

    def scrape(self) -> list[ScrapedListing]:
        """
        Main entry point: fetch and parse Craigslist listings across
        every configured region (config.sites.craigslist.regions —
        see the module docstring's "MULTI-STATE / MULTI-REGION
        COVERAGE" note).

        For each configured region:
          1. Fetch that region's search results page (single request
             — see LIVE-TESTING FINDINGS point 7 — politely rate-
             limited by fetch_page() same as every other request).
          2. Parse each listing card, apply passes_filters().
          3. Deduplicate by listing_id (both within and across
             regions), stopping once results_per_size matches are
             collected overall.

        Cross-source duplicate listings (e.g. the same item also
        found by another scraper) are deliberately NOT handled here —
        that's main.py's job via source+listing_id, same as every
        other scraper.

        Returns:
            List of ScrapedListing objects matching our filters,
            aggregated across all configured regions.
        """
        found: list[ScrapedListing] = []
        found_ids: set = set()
        max_results = self.config.search.results_per_size

        for region in self.regions:
            if len(found) >= max_results:
                break

            cards = self._fetch_cards(region)
            region_count = 0

            for item in cards:
                if len(found) >= max_results:
                    break
                try:
                    listing = self._parse_single_item(item)
                    if listing and listing.listing_id not in found_ids:
                        if self.passes_filters(listing):
                            found.append(listing)
                            found_ids.add(listing.listing_id)
                            region_count += 1
                except Exception:
                    # Skip individual listing parse errors — don't
                    # fail the whole batch.
                    continue

            print(f"  [Craigslist] region={region}: {region_count} matching listings")

        print(f"  [Craigslist] Found {len(found)} matching listings total "
              f"(regions={','.join(self.regions)})")
        return found
