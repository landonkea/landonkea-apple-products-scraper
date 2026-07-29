# ───────────────────────────────────────────────────────────────────
# Main orchestrator — runs all scrapers, analyzes prices, alerts
# ───────────────────────────────────────────────────────────────────
# This is the entry point.  When `mac-deal-scraper` is run (either
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
from datetime import datetime, timezone
from typing import Optional

from config import load_config, Config
from database import get_session, Listing

from scrapers.base import ScrapedListing
from scrapers.ebay import eBayScraper
from scrapers.swappa import SwappaScraper
from scrapers.apple_refurb import AppleRefurbScraper
from scrapers.backmarket import BackMarketScraper
from scrapers.mercari import MercariScraper
from scrapers.bestbuy import BestBuyScraper
from scrapers.offerup import OfferUpScraper

from price_analyzer import PriceAnalyzer
from notifier import Notifier


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
}


def get_enabled_scrapers(config: Config) -> list:
    """
    Get the scraper instances for all enabled sites.
    
    Checks config.sites.<site>.enabled for each marketplace.
    
    Args:
        config: The global Config object.
    
    Returns:
        A list of scraper instances, one per enabled site.
    """
    scrapers = []
    
    for source_name, scraper_class in SCRAPER_CLASSES.items():
        # Get the site config (e.g., config.sites.ebay)
        site_config = getattr(config.sites, source_name, None)
        
        if site_config and site_config.enabled:
            scrapers.append(scraper_class(config))
            print(f"  [Setup] Enabled scraper: {source_name}")
    
    if not scrapers:
        print("  ⚠️  No scrapers enabled. Check config.yaml.")
    
    return scrapers


def listing_to_db(db, listing: ScrapedListing, config: Config) -> Listing:
    """
    Save or update a ScrapedListing in the database.
    
    Uses "upsert" logic:
      - If a listing with the same source + listing_id exists,
        update it (price may have changed).
      - Otherwise, insert a new row.
    
    Args:
        db: Database session.
        listing: The parsed listing to save.
        config: Global config (for price thresholds).
    
    Returns:
        The saved Listing ORM object.
    """
    # Try to find an existing listing with the same source + ID
    existing = db.query(Listing).filter(
        Listing.source == listing.source,
        Listing.listing_id == listing.listing_id,
    ).first()
    
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
        )
        db.add(db_obj)
    
    # Mark great deals
    ram = listing.ram_gb or 64
    threshold = config.price.great_deal_usd.get(ram, 5000)
    db_obj.is_great_deal = listing.price_usd <= threshold
    
    db.commit()
    
    return db_obj


def find_new_listings(db, scraped: list[ScrapedListing]) -> list[Listing]:
    """
    Find listings we haven't seen before.
    
    Used to only alert on NEW deals, not ones we already know about.
    
    Args:
        db: Database session.
        scraped: List of ScrapedListings from the scraper.
    
    Returns:
        List of Listing ORM objects that are truly new.
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
    print(f"  MacBook Pro Deal Scraper — Starting Run")
    print(f"  {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"{'='*60}\n")
    
    # ── 1. Setup ───────────────────────────────────────────────
    print("📦 Initializing...")
    
    # Database
    db = get_session(config.database.url)
    print(f"  [DB] Connected to {config.database.url}")
    
    # Analyzer
    analyzer = PriceAnalyzer(config)
    
    # Notifier
    notifier = Notifier(config)
    
    # Scrapers
    scrapers = get_enabled_scrapers(config)
    print()
    
    # ── 2. Run all scrapers ────────────────────────────────────
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
    
    # ── 3. Save to database ────────────────────────────────────
    print("\n💾 Saving to database...")
    
    db_listings: list[Listing] = []
    for scraped in all_scraped:
        try:
            db_obj = listing_to_db(db, scraped, config)
            db_listings.append(db_obj)
        except Exception as e:
            print(f"  [DB] Error saving {scraped.title[:50]}: {e}")
            continue
    
    print(f"  Saved/updated {len(db_listings)} listings")
    
    # ── 4. Analyze prices ──────────────────────────────────────
    print("\n📊 Analyzing prices...")
    analyzed = analyzer.analyze(db_listings)
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
                  f"| {l.ram_gb}GB | {l.source} "
                  f"| Score: {l.deal_score}")
    
    # ── 5. Find truly new listings (never seen before) ─────────
    print("\n🆕 Checking for new listings...")
    new_listings = find_new_listings(db, all_scraped)
    print(f"  Truly new: {len(new_listings)}")
    
    # ── 6. Send alerts ─────────────────────────────────────────
    print("\n📬 Sending alerts...")
    
    # Only alert if:
    #   a) There are new listings, OR
    #   b) There are great deals (even if we've seen them before)
    has_great_deals = any(l.is_great_deal for l in top_deals)
    
    if new_listings or has_great_deals:
        notifier.send_alert(top_deals, stats)
    else:
        print("  No new listings or great deals — skipping alert.")
    
    # ── 7. Summary ─────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  ✅ Run complete — {datetime.now(timezone.utc).strftime('%H:%M UTC')}")
    print(f"  Total active listings in DB: {db.query(Listing).filter(Listing.is_active == True).count()}")
    print(f"{'='*60}\n")
    
    return 0


def main():
    """
    CLI entry point.
    
    Usage:
        mac-deal-scraper                    # Normal run
        mac-deal-scraper --config path.yaml  # Custom config path
        mac-deal-scraper --once              # Single run (for testing)
    
    When run via GitHub Actions, this is called automatically.
    """
    # Parse command-line args
    config_path = "config.yaml"
    
    if "--config" in sys.argv:
        idx = sys.argv.index("--config")
        if idx + 1 < len(sys.argv):
            config_path = sys.argv[idx + 1]
    
    print(f"Loading config from: {config_path}")
    
    # Check config exists
    if not os.path.exists(config_path):
        print(f"❌ Config file not found: {config_path}")
        print("   Copy config.yaml to the current directory.")
        sys.exit(1)
    
    # Load config
    config = load_config(config_path)
    
    # Run
    exit_code = run_scrape(config)
    sys.exit(exit_code)


# ── Allow running directly ────────────────────────────────────────
if __name__ == "__main__":
    main()
