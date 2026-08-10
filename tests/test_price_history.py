# ───────────────────────────────────────────────────────────────────
# Tests for per-listing price history (PriceHistory table)
# ───────────────────────────────────────────────────────────────────
# A lightweight (listing_id, price, timestamp) table, separate from
# DailyPriceStat's per-generation daily aggregate, that tracks every
# actual price CHANGE for one specific listing over time. These tests
# cover:
#   1. A brand-new listing gets its first price point recorded.
#   2. Re-recording the same price does NOT add a duplicate row.
#   3. A genuine price change DOES add a new row.
#   4. listing_to_db() (main.py) wires this in automatically.
#   5. Pruning old inactive listings also cleans up their history rows
#      (no orphaned PriceHistory rows left behind).
# ───────────────────────────────────────────────────────────────────

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import PriceConfig
from database import (
    Listing,
    PriceHistory,
    get_session,
    prune_old_inactive_listings,
    record_price_history,
)
from scrapers.base import ScrapedListing
import main as main_module


class FakeConfig:
    def __init__(self, price: PriceConfig):
        self.price = price


def _price_config(**overrides) -> PriceConfig:
    defaults = dict(
        absolute_max_usd=8000,
        great_deal_usd={128: 5000, 64: 4000},
        good_deal_usd={128: 5500, 64: 4500},
        top_deals_count=40,
    )
    defaults.update(overrides)
    return PriceConfig(**defaults)


def _temp_db():
    db_path = tempfile.mktemp(suffix=".db")
    return get_session(f"sqlite:///{db_path}"), db_path


def test_new_listing_records_first_price_point():
    db, db_path = _temp_db()
    try:
        listing = Listing(
            source="ebay", listing_id="abc", title="t",
            price_usd=1000.0, url="https://x",
        )
        db.add(listing)
        db.flush()

        added = record_price_history(db, listing, 1000.0)
        db.commit()

        assert added is True
        rows = db.query(PriceHistory).filter(PriceHistory.listing_id == listing.id).all()
        assert len(rows) == 1
        assert rows[0].price_usd == 1000.0
    finally:
        db.close()
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_unchanged_price_does_not_duplicate():
    db, db_path = _temp_db()
    try:
        listing = Listing(
            source="ebay", listing_id="abc", title="t",
            price_usd=1000.0, url="https://x",
        )
        db.add(listing)
        db.flush()

        record_price_history(db, listing, 1000.0)
        db.commit()
        added_again = record_price_history(db, listing, 1000.0)
        db.commit()

        assert added_again is False
        rows = db.query(PriceHistory).filter(PriceHistory.listing_id == listing.id).all()
        assert len(rows) == 1
    finally:
        db.close()
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_price_change_adds_new_row():
    db, db_path = _temp_db()
    try:
        listing = Listing(
            source="ebay", listing_id="abc", title="t",
            price_usd=1000.0, url="https://x",
        )
        db.add(listing)
        db.flush()

        record_price_history(db, listing, 1000.0)
        db.commit()

        listing.price_usd = 900.0
        added = record_price_history(db, listing, 900.0)
        db.commit()

        assert added is True
        rows = (
            db.query(PriceHistory)
            .filter(PriceHistory.listing_id == listing.id)
            .order_by(PriceHistory.recorded_at)
            .all()
        )
        assert [r.price_usd for r in rows] == [1000.0, 900.0]
    finally:
        db.close()
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_listing_to_db_writes_price_history():
    """main.py's listing_to_db() should write a PriceHistory row
    alongside the upsert, both for new listings and for re-scrapes
    where the price changed."""
    db, db_path = _temp_db()
    try:
        config = FakeConfig(_price_config())

        scraped = ScrapedListing(
            source="ebay", listing_id="abc123", title="MacBook Pro",
            price_usd=5000.0, url="https://ebay.com/x", condition="Used",
            ram_gb=128, storage_gb=1024, screen_size=14.0, chip="M5 Max",
            location=None, cpu_cores=None, gpu_cores=None,
        )

        db_obj, old_price = main_module.listing_to_db(db, scraped, config)
        assert old_price is None
        history = db.query(PriceHistory).filter(PriceHistory.listing_id == db_obj.id).all()
        assert len(history) == 1
        assert history[0].price_usd == 5000.0

        # Re-scrape with a price drop -- should add a second row.
        scraped.price_usd = 4500.0
        db_obj2, old_price2 = main_module.listing_to_db(db, scraped, config)
        assert old_price2 == 5000.0
        history2 = (
            db.query(PriceHistory)
            .filter(PriceHistory.listing_id == db_obj2.id)
            .order_by(PriceHistory.recorded_at)
            .all()
        )
        assert [h.price_usd for h in history2] == [5000.0, 4500.0]

        # Re-scrape again at the SAME price -- no new row.
        db_obj3, _ = main_module.listing_to_db(db, scraped, config)
        history3 = db.query(PriceHistory).filter(PriceHistory.listing_id == db_obj3.id).all()
        assert len(history3) == 2
    finally:
        db.close()
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_pruning_removes_orphaned_price_history():
    db, db_path = _temp_db()
    try:
        old_time = datetime.now(timezone.utc) - timedelta(days=200)
        listing = Listing(
            source="ebay", listing_id="old1", title="old",
            price_usd=1000.0, url="https://x",
            is_active=False, last_seen_at=old_time,
        )
        db.add(listing)
        db.flush()
        db.add(PriceHistory(listing_id=listing.id, price_usd=1000.0))
        db.commit()

        listing_id = listing.id
        deleted = prune_old_inactive_listings(db)

        assert deleted == 1
        assert db.query(Listing).filter(Listing.id == listing_id).first() is None
        assert db.query(PriceHistory).filter(PriceHistory.listing_id == listing_id).count() == 0
    finally:
        db.close()
        if os.path.exists(db_path):
            os.unlink(db_path)
