# ───────────────────────────────────────────────────────────────────
# Main orchestrator — runs all scrapers, analyzes prices, alerts
# ───────────────────────────────────────────────────────────────────
# This is the entry point.  When `apple-product-scraper` is run (either
# locally or via GitHub Actions), this script:
#
#   1. Loads config.yaml
#   2. Initializes all scrapers, database, analyzer, notifier
#   3. Runs every enabled scraper
#   4. Saves new/updated listings to the database
#   5. Analyzes prices and compute deal scores
#   6. Sends alerts for the best deals
#   7. Prints a summary
# ───────────────────────────────────────────────────────────────────

import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

from config import load_config, Config
from database import (
    get_session,
    Listing,
    prune_old_inactive_listings,
    record_price_history,
    RETENTION_DAYS,
)

from scrapers.base import ScrapedListing
from scrapers.ebay import eBayScraper
from scrapers.swappa import SwappaScraper
from scrapers.apple_refurb import AppleRefurbScraper
from scrapers.backmarket import BackMarketScraper
from scrapers.mercari import MercariScraper
from scrapers.bestbuy import BestBuyScraper
from scrapers.offerup import OfferUpScraper
from scrapers.newegg import NeweggScraper
from scrapers.gazelle import GazelleScraper
from scrapers.craigslist import CraigslistScraper
from scrapers.facebook import FacebookMarketplaceScraper

from price_analyzer import PriceAnalyzer, is_meaningful_price_drop
from notifier import Notifier
from stats_tracker import record_daily_stats
from pages_generator import generate_pages_data
from watchlist import (
    load_watchlist,
    save_watchlist,
    match_watchlist_entries,
    find_watchlist_alerts,
    record_watchlist_alerts,
    watchlist_path_for_environment,
)


# ── Scraper registry ──────────────────────────────────────────────
# Maps source names to scraper classes.
# When you add a new scraper, register it here.
SCRAPER_CLASSES = {
    "ebay": eBayScraper,
    "swappa": SwappaScraper,
    "apple_refurb": AppleRefurbScraper,
    "backmarket": BackMarketScraper,
    "mercari": MercariScraper,
    "bestbuy": BestBuyScraper,
    "offerup": OfferUpScraper,
    "newegg": NeweggScraper,
    "gazelle": GazelleScraper,
    "craigslist": CraigslistScraper,
    # STUB — requires FACEBOOK_SESSION_COOKIE to do anything; stays
    # inert (returns no listings) until that's set. See
    # scrapers/facebook.py and docs/marketplace-setup.md. Also
    # `enabled: false` in config.yaml, so it won't even run by default.
    "facebook": FacebookMarketplaceScraper,
}


def get_enabled_scrapers(config: Config) -> list:
    """
    Get the scraper instances for all enabled sites applicable to the
    active search's product type.

    Checks config.sites.<site>.enabled for each marketplace, and
    skips a site if its applicable_product_types is set and doesn't
    include the active search's product_type (see SiteConfig in
    config.py — this is how an Apple-only storefront like Apple
    Refurb automatically sits out a future non-electronics search
    instead of wasting a request and returning zero every time).

    Args:
        config: The global Config object. config.search must already
            be set to the active SearchConfig.

    Returns:
        A list of scraper instances, one per applicable enabled site.
    """
    scrapers = []
    product_type = config.search.product_type

    for source_name, scraper_class in SCRAPER_CLASSES.items():
        # Get the site config (e.g., config.sites.ebay)
        site_config = getattr(config.sites, source_name, None)
        if not (site_config and site_config.enabled):
            continue

        applicable = site_config.applicable_product_types
        if applicable is not None and product_type not in applicable:
            continue

        scrapers.append(scraper_class(config))
        print(f"  [Setup] Enabled scraper: {source_name}")

    if not scrapers:
        print("  ⚠️  No scrapers enabled. Check config.yaml.")

    return scrapers


def listing_to_db(db, listing: ScrapedListing,
                   config: Config) -> tuple[Listing, Optional[float]]:
    """
    Save or update a ScrapedListing in the database.

    Uses "upsert" logic:
      - If a listing with the same source + listing_id exists,
        update it (price may have changed).
      - Otherwise, insert a new row.

    PRICE HISTORY NOTE: the existing row's price_usd is overwritten
    on every re-scrape with no history preserved elsewhere -- the
    caller needs the price it's ABOUT to overwrite (to detect a price
    drop) before that happens, so this captures it up front and hands
    it back rather than silently losing it.

    Args:
        db: Database session.
        listing: The parsed listing to save.
        config: Global config (for price thresholds).

    Returns:
        A tuple of (the saved Listing ORM object, the listing's price
        immediately before this update -- or None if this is a
        brand-new listing with no prior price to compare against).
    """
    # Try to find an existing listing with the same source + ID
    existing = db.query(Listing).filter(
        Listing.source == listing.source,
        Listing.listing_id == listing.listing_id,
    ).first()

    # Captured BEFORE any overwrite below -- None means "never seen
    # before", which the caller uses to know a "price drop" can't
    # apply (see is_meaningful_price_drop in price_analyzer.py).
    old_price: Optional[float] = existing.price_usd if existing else None

    if existing:
        # Update existing listing
        existing.title = listing.title
        existing.price_usd = listing.price_usd
        existing.url = listing.url
        existing.condition = listing.condition
        existing.ram_gb = listing.ram_gb
        existing.storage_gb = listing.storage_gb
        existing.screen_size = listing.screen_size
        existing.chip = listing.chip
        existing.cpu_cores = listing.cpu_cores
        existing.gpu_cores = listing.gpu_cores
        existing.size = listing.size
        existing.brand = listing.brand
        existing.color = listing.color
        existing.last_seen_at = datetime.now(timezone.utc)
        existing.is_active = True
        db_obj = existing
    else:
        # Create new listing
        db_obj = Listing(
            source=listing.source,
            listing_id=listing.listing_id,
            title=listing.title,
            price_usd=listing.price_usd,
            url=listing.url,
            condition=listing.condition,
            ram_gb=listing.ram_gb,
            storage_gb=listing.storage_gb,
            screen_size=listing.screen_size,
            chip=listing.chip,
            cpu_cores=listing.cpu_cores,
            gpu_cores=listing.gpu_cores,
            size=listing.size,
            brand=listing.brand,
            color=listing.color,
        )
        db.add(db_obj)
        # Flush so db_obj.id is populated before record_price_history
        # needs it (a brand-new row has no id until the INSERT runs).
        db.flush()

    # Mark great deals
    ram = listing.ram_gb or 64
    threshold = config.price.great_deal_usd.get(ram, 5000)
    db_obj.is_great_deal = listing.price_usd <= threshold

    # Per-listing price history (separate from DailyPriceStat's daily
    # per-generation aggregate) -- only writes a new row when the
    # price is new or has changed, see record_price_history()'s
    # docstring for why.
    record_price_history(db, db_obj, listing.price_usd)

    db.commit()

    return db_obj, old_price


def find_new_listings(db, scraped: list[ScrapedListing]) -> list[ScrapedListing]:
    """
    Find listings we haven't seen before.

    Used to only alert on NEW deals, not ones we already know about.

    Args:
        db: Database session.
        scraped: List of ScrapedListings from the scraper.

    Returns:
        The subset of `scraped` (still ScrapedListing objects, not
        yet saved as DB Listing rows) whose source+listing_id doesn't
        already exist in the database.
    """
    new_listings = []
    
    for sl in scraped:
        existing = db.query(Listing).filter(
            Listing.source == sl.source,
            Listing.listing_id == sl.listing_id,
        ).first()
        
        if not existing:
            new_listings.append(sl)
    
    return new_listings


# A great deal that goes from "first seen" to "expired" (not seen
# again) within this many hours was very likely bought by someone
# else, not just a stale/removed listing -- worth its own alert since
# it's a strong signal the price was genuinely good. 24h is generous
# enough that a listing seen once, then expired on the very next
# 6-hour scrape (the fastest possible "gone"), and even one seen a
# couple of scrapes later still counts, while a deal that lingered for
# days before quietly expiring (more likely just delisted/expired,
# not sold) does not.
SCOOPED_DEAL_HOURS = 24


def expire_stale_listings(db, hours: int = 72) -> tuple[int, list[Listing]]:
    """
    Mark listings inactive if we haven't seen them again in `hours`.

    A listing that hasn't shown up in a scrape for 72+ hours is
    probably sold or removed, so it's excluded from "current deals"
    going forward. Rows are kept (not deleted) — daily price-stat
    history relies on past listings still being in the table.

    ALSO flags "scooped" great deals: listings that were flagged
    is_great_deal AND whose entire visible lifetime (first_seen_at to
    last_seen_at, i.e. from when we first saw it to the last time we
    saw it before it went stale) was under SCOOPED_DEAL_HOURS. That
    combination — a great price that vanished fast — is a strong
    signal someone else bought it, which is worth surfacing on its
    own (see notifier.py's send_scooped_deal_alert).

    Args:
        db: Database session.
        hours: How long a listing can go unseen before expiring.

    Returns:
        A tuple of (number of listings just marked inactive, the
        subset of those that were great deals scooped up fast).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    stale = (
        db.query(Listing)
        .filter(Listing.is_active == True, Listing.last_seen_at < cutoff)
        .all()
    )

    scooped: list[Listing] = []
    for listing in stale:
        if (
            listing.is_great_deal
            and listing.first_seen_at is not None
            and listing.last_seen_at is not None
            and (listing.last_seen_at - listing.first_seen_at)
            <= timedelta(hours=SCOOPED_DEAL_HOURS)
        ):
            scooped.append(listing)
        listing.is_active = False

    db.commit()
    return len(stale), scooped


def _run_one_search(
    config: Config,
    search_config,
    db,
    watchlist_entries: Optional[list[dict]] = None,
    watchlist_matches: Optional[list[tuple[dict, Listing]]] = None,
) -> None:
    """
    Run one product search end-to-end: scrape, save, analyze, alert.

    WHAT: Everything needed to go from "a search config for one
    product" (e.g. MacBook Pro or iPhone) to alerts being sent, for
    that product only — scrape all enabled sites, save/upsert results
    to the DB, record daily price stats, compute deal scores, and
    notify if there are new listings or great deals.
    HOW: Points `config.search` at this iteration's `search_config`
    (scrapers/analyzer/notifier all read product-specific settings off
    `config.search`), builds fresh per-product `PriceAnalyzer` and
    `Notifier` instances, runs every enabled scraper, upserts results,
    records stats, analyzes prices, and finally sends alerts if
    warranted.
    WHY: `run_scrape()` used to inline this whole pipeline inside its
    `for search_config in config.searches:` loop, making it a single
    ~150-line function that mixed one-time setup with per-product
    work. Extracting the loop body here means `run_scrape()` is now
    just "setup, then run one search per configured product, then
    export," and this function's job — one product's full pipeline —
    can be read (and eventually tested) on its own.

    Args:
        config: The global Config object. `config.search` is mutated
            to point at `search_config` for the duration of this call,
            matching the pre-existing behavior of the original loop.
        search_config: The per-product search settings for this run
            (product name, screen sizes, chip, RAM, etc.).
        db: Database session, shared across all searches in this run.
        watchlist_entries: All watchlist entries for this whole run
            (see watchlist.load_watchlist()) -- a tracked URL isn't
            tied to any one product search, so every search checks
            the same full list against its own listings.
        watchlist_matches: Shared accumulator this call appends
            (entry, listing) matches into -- watchlist alerting/
            saving happens once, after every product search has run
            (see run_scrape()), not per-product.

    Both watchlist_* args default to None (treated as "no watchlist
    for this call") so this function stays easy to call/test in
    isolation without a live watchlist to thread through.
    """
    if watchlist_entries is None:
        watchlist_entries = []
    if watchlist_matches is None:
        watchlist_matches = []

    product_name = search_config.product_name
    print(f"\n{'─'*60}")
    print(f"  Searching for: {product_name}")
    print(f"{'─'*60}\n")

    # Create a temporary config with this search
    config.search = search_config

    # Analyzer (one per product)
    analyzer = PriceAnalyzer(config)

    # Notifier (one per product)
    notifier = Notifier(config)

    # Scrapers
    scrapers = get_enabled_scrapers(config)

    # ── 2a. Run all scrapers ───────────────────────────────
    print("🔍 Scraping marketplaces...")

    all_scraped: list[ScrapedListing] = []

    for scraper in scrapers:
        print(f"\n  ── {scraper.source_name.upper()} ──")
        try:
            found = scraper.scrape()
            all_scraped.extend(found)
        except Exception as e:
            print(f"  ❌ {scraper.source_name} failed: {e}")
            continue

    print(f"\n  Total raw listings found: {len(all_scraped)}")

    # ── 2b. Save to database ───────────────────────────────
    print("\n💾 Saving to database...")

    db_listings: list[Listing] = []
    # Listings that ALREADY existed and whose price just dropped by
    # more than config.price_drop's thresholds -- a separate alert
    # type from "new deal found" (see is_meaningful_price_drop).
    price_drops: list[tuple[Listing, float]] = []
    for scraped in all_scraped:
        try:
            db_obj, old_price = listing_to_db(db, scraped, config)
            db_listings.append(db_obj)
            # `old_price is not None` first so mypy narrows old_price
            # to float within this branch (is_meaningful_price_drop
            # already returns False for None, but that fact isn't
            # visible to the type checker across the call boundary).
            if old_price is not None and is_meaningful_price_drop(
                old_price, float(db_obj.price_usd), config
            ):
                price_drops.append((db_obj, old_price))
        except Exception as e:
            print(f"  [DB] Error saving {scraped.title[:50]}: {e}")
            continue

    print(f"  Saved/updated {len(db_listings)} listings")
    if price_drops:
        print(f"  💧 Detected {len(price_drops)} meaningful price drop(s)")

    # ── 2b-1. Cross-reference the watchlist ─────────────────
    # Checked against every product search's own listings (a tracked
    # URL might be for a product this search wasn't even looking for,
    # e.g. a different RAM/storage combo) -- matches accumulate across
    # all searches and are alerted on once at the end of run_scrape().
    if watchlist_entries:
        watchlist_matches.extend(
            match_watchlist_entries(watchlist_entries, db_listings)
        )

    # ── 2b-2. Record daily price stats (for trend charts) ──
    stat_rows = record_daily_stats(db, search_config, db_listings)
    if stat_rows:
        print(f"  [Stats] Updated {stat_rows} daily price-stat group(s)")

    # ── 2c. Analyze prices ─────────────────────────────────
    print("\n📊 Analyzing prices...")
    analyzer.analyze(db_listings)
    stats = analyzer.get_stats()

    print(f"  Listings analyzed: {stats['count']}")
    print(f"  Price range: ${stats['min']:,.0f} – ${stats['max']:,.0f}")
    print(f"  Median: ${stats['median']:,.0f} | Mean: ${stats['mean']:,.0f}")

    # Show top deals
    top_deals = analyzer.get_top_deals()
    if top_deals:
        print(f"\n  🔥 Top {len(top_deals)} Deals:")
        for i, l in enumerate(top_deals[:5], 1):
            emoji = "🔥" if l.is_great_deal else "💰"
            print(f"    {emoji} #{i}: ${l.price_usd:,.0f} "
                  f"| {l.source} "
                  f"| Score: {l.deal_score}")

    # ── 2d. Find truly new listings ────────────────────────
    print("\n🆕 Checking for new listings...")
    new_listings = find_new_listings(db, all_scraped)
    print(f"  Truly new: {len(new_listings)}")

    # ── 2e. Send alerts ────────────────────────────────────
    print("\n📬 Sending alerts...")

    has_great_deals = any(l.is_great_deal for l in top_deals)

    if config.dry_run:
        # --dry-run/--no-alert: run the full pipeline (scrape, save,
        # analyze) but never actually post -- lets you test locally
        # against the real config.yaml/database without spamming the
        # real Discord channel.
        if new_listings or has_great_deals:
            print(f"  [dry-run] Would send alert for {len(top_deals)} top deal(s) — skipped.")
        else:
            print("  No new listings or great deals — skipping alert.")
        if price_drops:
            print(f"  [dry-run] Would send price-drop alert for {len(price_drops)} listing(s) — skipped.")
    else:
        if new_listings or has_great_deals:
            notifier.send_alert(top_deals, stats)
        else:
            print("  No new listings or great deals — skipping alert.")

        # ── 2e-2. Send price-drop alerts ───────────────────
        # Independent of the "new deal" condition above -- a price
        # drop on a listing we already know about is worth its own
        # alert even when nothing new was found this run.
        if price_drops:
            print(f"\n💧 Sending price-drop alerts for {len(price_drops)} listing(s)...")
            notifier.send_price_drop_alert(price_drops)


def run_scrape(config: Config) -> int:
    """
    Run the full scrape cycle.

    This is the main function called by the CLI or GitHub Action.

    Args:
        config: The global Config object.

    Returns:
        0 on success, 1 on error.
    """
    print(f"\n{'='*60}")
    print("  Apple Product Scraper — Starting Run")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    # Print the active environment prominently — this is the single
    # most important line in the banner for telling a real production
    # run apart from a local dev/staging test run at a glance.
    print(f"  Environment: {config.environment}")
    print(f"{'='*60}\n")

    # ── 1. Setup ───────────────────────────────────────────────
    print("📦 Initializing...")

    # Database
    db = get_session(config.database.url)
    print(f"  [DB] Connected to {config.database.url}")

    # Expire listings we haven't seen in 72+ hours (probably sold/removed).
    # Rows are kept, just excluded from "current deals" — price history
    # stays intact for trend charts.
    expired_count, scooped_deals = expire_stale_listings(db, hours=72)
    print(f"  [DB] Expired {expired_count} listings not seen in 72+ hours")

    if scooped_deals:
        print(f"  🏃 {len(scooped_deals)} great deal(s) expired within "
              f"{SCOOPED_DEAL_HOURS}h of first being seen — likely scooped:")
        for scooped_listing in scooped_deals:
            print(f"      • ${scooped_listing.price_usd:,.0f} | "
                  f"{scooped_listing.source} | {scooped_listing.title[:60]}")

        if config.dry_run:
            print(f"  [dry-run] Would send scooped-deal alert for "
                  f"{len(scooped_deals)} listing(s) — skipped.")
        else:
            notifier = Notifier(config)
            notifier.send_scooped_deal_alert(scooped_deals)

    # Permanently delete listings that have been inactive for a long
    # time (see prune_old_inactive_listings() in database.py for why
    # this is safe — the trend charts read from a separate, already-
    # aggregated table these rows never touch).
    pruned_count = prune_old_inactive_listings(db)
    print(f"  [DB] Pruned {pruned_count} listings inactive for {RETENTION_DAYS}+ days")

    print()

    # ── 2. Run search for each product ─────────────────────────
    # Watchlist entries are global (not per-product), so they're
    # loaded once here and matched against every product search's
    # listings, then alerted on/saved once after the loop -- see
    # _run_one_search()'s docstring and watchlist.py's module
    # docstring.
    watchlist_path = watchlist_path_for_environment(config.environment)
    watchlist_entries = load_watchlist(watchlist_path)
    watchlist_matches: list[tuple[dict, Listing]] = []

    for search_config in config.searches:
        _run_one_search(config, search_config, db, watchlist_entries, watchlist_matches)

    # ── 2e-3. Send watchlist alerts ─────────────────────────────
    if watchlist_entries:
        watchlist_alerts = find_watchlist_alerts(watchlist_matches)
        if watchlist_alerts:
            print(f"\n🔭 {len(watchlist_alerts)} watchlist listing(s) newly "
                  f"matched or changed price...")
            if config.dry_run:
                print(f"  [dry-run] Would send watchlist alert for "
                      f"{len(watchlist_alerts)} listing(s) — skipped.")
            else:
                notifier = Notifier(config)
                notifier.send_watchlist_alert(watchlist_alerts)
                record_watchlist_alerts(watchlist_alerts)
        # Persist regardless of whether anything was alert-worthy this
        # run -- match_watchlist_entries() may have backfilled a fresh
        # entry's source/listing_id even when its price didn't change
        # (see watchlist.py's module docstring), and that resolution
        # should stick for future runs. Skipped entirely in dry-run so
        # a local test run never touches the real watchlist file.
        if not config.dry_run:
            save_watchlist(watchlist_entries, watchlist_path)

    # ── 2f. Export price-trend data for the GitHub Pages site ──
    print("\n📈 Updating price trend charts...")
    exported_rows = generate_pages_data(db)
    print(f"  [Pages] Exported {exported_rows} daily price-stat rows to docs/data/daily_stats.json")

    # ── 3. Summary ─────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  ✅ Run complete — {datetime.now(timezone.utc).strftime('%H:%M UTC')}")
    print(f"  Total active listings in DB: {db.query(Listing).filter(Listing.is_active == True).count()}")
    print(f"{'='*60}\n")
    
    return 0


def main():
    """
    CLI entry point.

    Usage:
        apple-product-scraper                    # Normal run
        apple-product-scraper --config path.yaml  # Custom config path
        apple-product-scraper --once              # Single run (for testing)
        apple-product-scraper --dry-run           # Scrape/save/analyze but
                                                     # never send Discord/email
                                                     # alerts (--no-alert works
                                                     # too, same behavior)

    When run via GitHub Actions, this is called automatically.
    """
    # Parse command-line args
    config_path = "config.yaml"

    if "--config" in sys.argv:
        idx = sys.argv.index("--config")
        if idx + 1 < len(sys.argv):
            config_path = sys.argv[idx + 1]

    # --dry-run and --no-alert are accepted as synonyms -- both mean
    # "run the real pipeline against the real config, but never
    # actually post to Discord/email." Useful for testing scraper/
    # scoring changes locally without spamming a live channel.
    dry_run = "--dry-run" in sys.argv or "--no-alert" in sys.argv

    print(f"Loading config from: {config_path}")

    # Check config exists
    if not os.path.exists(config_path):
        print(f"❌ Config file not found: {config_path}")
        print("   Copy config.yaml to the current directory.")
        sys.exit(1)

    # Load config
    config = load_config(config_path)
    config.dry_run = dry_run
    if dry_run:
        print("🧪 --dry-run/--no-alert set: alerts will be logged but not sent.")

    # Run
    exit_code = run_scrape(config)
    sys.exit(exit_code)


# ── Allow running directly ────────────────────────────────────────
if __name__ == "__main__":
    main()
