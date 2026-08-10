# ───────────────────────────────────────────────────────────────────
# Tests for database models and operations
# ───────────────────────────────────────────────────────────────────

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from database import get_session, Listing, Base, get_engine, prune_old_inactive_listings, RETENTION_DAYS
from sqlalchemy import inspect


def test_create_tables():
    """Test that database tables are created correctly."""
    # Use a temporary file for the database
    db_path = tempfile.mktemp(suffix=".db")
    db_url = f"sqlite:///{db_path}"
    
    try:
        engine = get_engine(db_url)
        Base.metadata.create_all(engine)
        
        # Check that the listings table exists
        inspector = inspect(engine)
        table_names = inspector.get_table_names()
        assert "listings" in table_names
        
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_create_and_query_listing():
    """Test creating and querying a listing."""
    db_path = tempfile.mktemp(suffix=".db")
    db_url = f"sqlite:///{db_path}"
    
    try:
        db = get_session(db_url)
        
        # Create a listing
        listing = Listing(
            source="ebay",
            listing_id="test_item_123",
            title='MacBook Pro 14" M5 Max 128GB',
            price_usd=4999.99,
            url="https://ebay.com/itm/123",
            condition="Used",
            ram_gb=128,
            storage_gb=2048,
            screen_size=14.0,
            chip="M5 Max",
            deal_score=95.0,
            is_great_deal=True,
        )
        db.add(listing)
        db.commit()
        
        # Query it back
        found = db.query(Listing).filter(
            Listing.listing_id == "test_item_123"
        ).first()
        
        assert found is not None
        assert found.source == "ebay"
        assert found.price_usd == 4999.99
        assert found.ram_gb == 128
        assert found.is_great_deal is True
        
    finally:
        db.close()
        if os.path.exists(db_path):
            os.unlink(db_path)


def _make_test_db():
    db_path = tempfile.mktemp(suffix=".db")
    db_url = f"sqlite:///{db_path}"
    return get_session(db_url), db_path


def test_prune_deletes_long_inactive_listings():
    """A listing inactive for well over the retention window gets deleted."""
    db, db_path = _make_test_db()
    try:
        old_cutoff = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS + 10)
        listing = Listing(
            source="ebay", listing_id="old_dead", title="Old dead listing",
            price_usd=100.0, url="https://ebay.com/itm/old", is_active=False,
        )
        db.add(listing)
        db.commit()
        # last_seen_at has an onupdate default set at commit time — force it
        # back to a genuinely old timestamp to simulate a long-dead listing.
        db.query(Listing).filter(Listing.listing_id == "old_dead").update(
            {"last_seen_at": old_cutoff}
        )
        db.commit()

        deleted = prune_old_inactive_listings(db)
        assert deleted == 1
        assert db.query(Listing).filter(Listing.listing_id == "old_dead").first() is None
    finally:
        db.close()
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_prune_keeps_recently_inactive_listings():
    """A listing that only just went inactive is NOT deleted yet."""
    db, db_path = _make_test_db()
    try:
        listing = Listing(
            source="ebay", listing_id="recently_dead", title="Recently dead listing",
            price_usd=100.0, url="https://ebay.com/itm/recent", is_active=False,
        )
        db.add(listing)
        db.commit()

        deleted = prune_old_inactive_listings(db)
        assert deleted == 0
        assert db.query(Listing).filter(Listing.listing_id == "recently_dead").first() is not None
    finally:
        db.close()
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_prune_never_deletes_active_listings():
    """An active listing is never deleted, no matter how old last_seen_at is."""
    db, db_path = _make_test_db()
    try:
        very_old = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS * 10)
        listing = Listing(
            source="ebay", listing_id="old_but_active", title="Old but still active",
            price_usd=100.0, url="https://ebay.com/itm/active", is_active=True,
        )
        db.add(listing)
        db.commit()
        db.query(Listing).filter(Listing.listing_id == "old_but_active").update(
            {"last_seen_at": very_old}
        )
        db.commit()

        deleted = prune_old_inactive_listings(db)
        assert deleted == 0
        assert db.query(Listing).filter(Listing.listing_id == "old_but_active").first() is not None
    finally:
        db.close()
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_prune_respects_custom_days_argument():
    db, db_path = _make_test_db()
    try:
        ten_days_ago = datetime.now(timezone.utc) - timedelta(days=10)
        listing = Listing(
            source="ebay", listing_id="ten_days_dead", title="Ten days dead",
            price_usd=100.0, url="https://ebay.com/itm/ten", is_active=False,
        )
        db.add(listing)
        db.commit()
        db.query(Listing).filter(Listing.listing_id == "ten_days_dead").update(
            {"last_seen_at": ten_days_ago}
        )
        db.commit()

        # Default 180-day window: not old enough yet.
        assert prune_old_inactive_listings(db) == 0
        # A tighter 5-day window: now it qualifies.
        assert prune_old_inactive_listings(db, days=5) == 1
    finally:
        db.close()
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_deduplication():
    """Test that duplicate listings are not created."""
    db_path = tempfile.mktemp(suffix=".db")
    db_url = f"sqlite:///{db_path}"
    
    try:
        db = get_session(db_url)
        
        # Create first listing
        listing1 = Listing(
            source="ebay",
            listing_id="dup_test",
            title="Original Listing",
            price_usd=5000.00,
            url="https://ebay.com/itm/dup",
        )
        db.add(listing1)
        db.commit()
        
        # Try to create a duplicate (same source + listing_id)
        listing2 = Listing(
            source="ebay",
            listing_id="dup_test",
            title="Updated Listing",  # Different title
            price_usd=4800.00,        # Different price
            url="https://ebay.com/itm/dup",
        )
        db.add(listing2)
        
        # This should raise an IntegrityError because of the
        # unique constraint on (source, listing_id)
        import sqlalchemy.exc
        try:
            db.commit()
            # If no error, the test still passes — we handle this
            # in main.py via upsert logic
            pass
        except sqlalchemy.exc.IntegrityError:
            db.rollback()
        
        # We should only have one listing
        count = db.query(Listing).filter(
            Listing.listing_id == "dup_test"
        ).count()
        assert count == 1
        
    finally:
        db.close()
        if os.path.exists(db_path):
            os.unlink(db_path)
