# ───────────────────────────────────────────────────────────────────
# Daily price-stat tracker — feeds the trend charts
# ───────────────────────────────────────────────────────────────────
# Every scrape run, this rolls up the listings found for a search
# into one min/avg/max row per product generation per day (e.g.
# "2026-07-31, M5 Max, $3,008-$4,656-$7,139"). Charts read this
# table to plot low/avg/high over time.
# ───────────────────────────────────────────────────────────────────

import statistics
from datetime import datetime, timezone

from config import SearchConfig
from database import DailyPriceStat, Listing


def _group_key_for_listing(listing: Listing, search: SearchConfig) -> str | None:
    """
    Figure out which generation a listing belongs to.

    For chip-based searches (MacBook Pro), this is the parsed chip
    name (e.g. "M5 Max"). For model-keyword searches (iPhone), it's
    whichever configured keyword (e.g. "iPhone 17 Pro Max") appears
    in the title.

    Returns None if the listing doesn't match any tracked generation.
    """
    if search.chip_options:
        if listing.chip and listing.chip in search.chip_options:
            return listing.chip
        return None

    if search.model_keywords:
        title_lower = listing.title.lower()
        for keyword in search.model_keywords:
            if keyword.lower() in title_lower:
                return keyword
        return None

    return None


def record_daily_stats(db, search: SearchConfig, listings: list[Listing]) -> int:
    """
    Roll up today's listings into per-generation min/avg/max rows.

    Upserts one row per (today's date, group_key) — safe to call
    multiple times per day (e.g. once per 6-hour run); each call
    overwrites today's row with the latest numbers. Groups with zero
    matching listings this run are left untouched (a temporary site
    outage shouldn't wipe out a previously-good stat for today).

    Args:
        db: Database session.
        search: The SearchConfig this batch of listings came from.
        listings: Listings just scraped for this search (already
                  passed passes_filters).

    Returns:
        Number of (date, group_key) rows written/updated.
    """
    if not search.chip_options and not search.model_keywords:
        return 0  # Manually-configured search, no generation grouping to do.

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    by_group: dict[str, list[float]] = {}
    for listing in listings:
        key = _group_key_for_listing(listing, search)
        if key is None:
            continue
        by_group.setdefault(key, []).append(listing.price_usd)

    written = 0
    for group_key, prices in by_group.items():
        if not prices:
            continue

        row = (
            db.query(DailyPriceStat)
            .filter(DailyPriceStat.date == today, DailyPriceStat.group_key == group_key)
            .first()
        )
        if row is None:
            row = DailyPriceStat(date=today, product_name=search.product_name, group_key=group_key)
            db.add(row)

        row.product_name = search.product_name
        row.min_price = min(prices)
        row.avg_price = round(statistics.mean(prices), 2)
        row.max_price = max(prices)
        row.listing_count = len(prices)
        written += 1

    db.commit()
    return written
