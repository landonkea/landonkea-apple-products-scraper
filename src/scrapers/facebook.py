# ───────────────────────────────────────────────────────────────────
# Facebook Marketplace scraper — STUB (requires a login session cookie)
# ───────────────────────────────────────────────────────────────────
# Unlike every other scraper in this project (eBay, Swappa, Mercari,
# OfferUp, ...), Facebook Marketplace will not show search results to
# a logged-out visitor — it redirects to a login page. There's no
# public, unauthenticated way to search it.
#
# This file is intentionally a STUB. It does nothing (returns no
# listings) until a `FACEBOOK_SESSION_COOKIE` value is provided via
# environment variable / GitHub Secret. It is registered in main.py's
# SCRAPER_CLASSES and config.yaml already has `facebook: enabled:
# false`, so right now this scraper exists but stays fully inert —
# no network requests are ever made without a cookie configured.
#
# See docs/marketplace-setup.md for a beginner-friendly explanation
# of what a "session cookie" is and how to get one, once you're ready
# to wire this up for real with Claude's help.
# ───────────────────────────────────────────────────────────────────

from scrapers.base import BaseScraper, ScrapedListing
from config import Config


class FacebookMarketplaceScraper(BaseScraper):
    """
    STUB scraper for Facebook Marketplace — inert until configured.

    WHAT: Would scrape Facebook Marketplace search results for
    MacBook Pro / iPhone Pro Max listings, the same way ebay.py or
    offerup.py do for their marketplaces.

    HOW: Facebook Marketplace requires a logged-in browser session to
    view search results at all — there's no public search endpoint
    like eBay's or Swappa's. So instead of a username/password login
    flow (which is fragile, against most sites' terms, and risky to
    build without the account owner walking through it live), this
    scraper expects a session cookie value copied out of an already
    logged-in browser, provided via the `FACEBOOK_SESSION_COOKIE`
    environment variable (see config.py's `_load_env_secrets()` and
    `self.config.secrets["facebook_session_cookie"]`). Until that
    value is set, `scrape()` logs one clear, actionable line and
    returns an empty list — it never attempts a network request.

    WHY: The project owner is new to programming and hasn't set up a
    Facebook session cookie yet, and guessing at real login/session
    handling now would mean shipping untested, unverifiable code
    against a site that actively fights scrapers. This stub lets the
    scraper registry, config, and docs all exist and be reviewed now,
    while the actual credential and fetch/parse logic gets filled in
    later once the owner is walked through getting a real cookie.
    """

    def __init__(self, config: Config):
        """Initialize the Facebook Marketplace scraper."""
        super().__init__(config)
        self.source_name = "facebook"

    def scrape(self) -> list[ScrapedListing]:
        """
        Scrape Facebook Marketplace — or, without a session cookie, don't.

        WHAT: Returns a list of ScrapedListing objects found on
        Facebook Marketplace, matching the interface every other
        scraper implements.

        HOW: First checks `self.config.secrets.get("facebook_session_cookie")`.
        If it's missing (the default — nothing has been configured
        yet), prints one clear, actionable log line explaining exactly
        what env var to set and where to read how, then returns `[]`
        immediately without touching the network. If a cookie value
        IS present, the method would build a request/browser session
        that includes it and parse the results page — that part is a
        TODO below, since it can't be built (or tested) without a real
        cookie and a live look at Facebook's current search markup.

        WHY: A confidently-written fetch/parse implementation against
        a site we can't currently log into would be pure guesswork —
        untestable now, and likely wrong once real markup is checked
        against it later. Failing loud-but-harmless (a log line, no
        crash, no request) keeps this scraper safe to leave registered
        and `enabled: false` in config.yaml indefinitely, with a clear
        next step for whoever turns it on.

        Returns:
            A list of ScrapedListing objects (currently always empty
            until a session cookie is configured).
        """
        session_cookie = self.config.secrets.get("facebook_session_cookie")

        if not session_cookie:
            print(
                "  [Facebook Marketplace] Not configured — set "
                "FACEBOOK_SESSION_COOKIE to enable. See "
                "docs/marketplace-setup.md for how to get one."
            )
            return []

        # ── TODO: real implementation, once a session cookie exists ──
        # This is a rough sketch of how it would work, NOT functional
        # code — it hasn't been run against Facebook's real site, and
        # the actual markup/JSON shape will need to be checked live
        # (most likely via Playwright, like offerup.py, since
        # Marketplace is a heavy JS app) before this can work.
        #
        #   results: list[ScrapedListing] = []
        #   for screen_size in self.config.search.screen_sizes or [None]:
        #       url = self._build_search_url(screen_size)
        #
        #       # Attach the session cookie so the request looks like
        #       # it's coming from a logged-in browser. Exact cookie
        #       # name(s) depend on what's captured from dev tools —
        #       # see docs/marketplace-setup.md.
        #       self.session.cookies.set(
        #           "c_user", session_cookie, domain=".facebook.com"
        #       )
        #
        #       # Facebook Marketplace is a JS-heavy app, so plain
        #       # requests.get() likely won't show real listings —
        #       # probably needs fetch_with_playwright() instead,
        #       # with the cookie injected into the browser context.
        #       html = self.fetch_page(url)
        #       soup = self.parse_html(html)
        #
        #       for item in soup.select(".some-listing-selector"):  # TODO
        #           title = item.select_one(".title")?.get_text(strip=True)
        #           ...
        #           specs = self.parse_common_specs(title)
        #           listing = ScrapedListing(
        #               source=self.source_name,
        #               listing_id=...,
        #               title=title,
        #               price_usd=...,
        #               url=...,
        #               condition=None,
        #               location=...,
        #               **specs,
        #           )
        #           if self.passes_filters(listing):
        #               results.append(listing)
        #   return results

        return []
