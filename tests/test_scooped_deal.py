# ───────────────────────────────────────────────────────────────────
# Tests for the "scooped great deal" alert
# ───────────────────────────────────────────────────────────────────
# When a great deal expires (goes inactive) within SCOOPED_DEAL_HOURS
# of first being seen, it's flagged as likely "scooped" (bought by
# someone else) -- a signal not previously surfaced anywhere. Covers:
#   1. A great deal that expires fast IS flagged.
#   2. A great deal that lingers for a long time before expiring is
#      NOT flagged.
#   3. A non-great-deal listing that expires fast is NOT flagged.
#   4. expire_stale_listings() still marks everything inactive and
#      returns the right total count regardless of scooped status.
#   5. The Discord message builder produces sane content for a batch
#      of scooped deals.
# ───────────────────────────────────────────────────────────────────

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from database import Listing, get_session
from notifier import Notifier
import main as main_module


def _temp_db():
    db_path = tempfile.mktemp(suffix=".db")
    return get_session(f"sqlite:///{db_path}"), db_path


def _make_listing(db, *, is_great_deal, first_seen_at, last_seen_at, price=4500.0):
    listing = Listing(
        source="ebay",
        listing_id=f"id-{first_seen_at.isoformat()}-{is_great_deal}",
        title="MacBook Pro 14 M5 Max 128GB",
        price_usd=price,
        url="https://ebay.com/itm/1",
        is_great_deal=is_great_deal,
        is_active=True,
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
    )
    db.add(listing)
    db.commit()
    return listing


def test_fast_expiring_great_deal_is_flagged_as_scooped():
    db, db_path = _temp_db()
    try:
        now = datetime.now(timezone.utc)
        # First seen 80h ago, last seen 76h ago (4h lifetime, well
        # under the 24h scooped threshold) -- stale relative to the
        # 72h expiry cutoff.
        _make_listing(
            db, is_great_deal=True,
            first_seen_at=now - timedelta(hours=80),
            last_seen_at=now - timedelta(hours=76),
        )

        expired_count, scooped = main_module.expire_stale_listings(db, hours=72)

        assert expired_count == 1
        assert len(scooped) == 1
    finally:
        db.close()
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_slow_expiring_great_deal_is_not_scooped():
    db, db_path = _temp_db()
    try:
        now = datetime.now(timezone.utc)
        # Lingered for 10 days before its last sighting -- not a fast
        # disappearance, just an old listing going stale.
        _make_listing(
            db, is_great_deal=True,
            first_seen_at=now - timedelta(days=20),
            last_seen_at=now - timedelta(days=10),
        )

        expired_count, scooped = main_module.expire_stale_listings(db, hours=72)

        assert expired_count == 1
        assert len(scooped) == 0
    finally:
        db.close()
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_non_great_deal_expiring_fast_is_not_scooped():
    db, db_path = _temp_db()
    try:
        now = datetime.now(timezone.utc)
        _make_listing(
            db, is_great_deal=False,
            first_seen_at=now - timedelta(hours=80),
            last_seen_at=now - timedelta(hours=76),
        )

        expired_count, scooped = main_module.expire_stale_listings(db, hours=72)

        assert expired_count == 1
        assert len(scooped) == 0
    finally:
        db.close()
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_active_listing_within_window_is_untouched():
    db, db_path = _temp_db()
    try:
        now = datetime.now(timezone.utc)
        _make_listing(
            db, is_great_deal=True,
            first_seen_at=now - timedelta(hours=2),
            last_seen_at=now - timedelta(hours=1),
        )

        expired_count, scooped = main_module.expire_stale_listings(db, hours=72)

        assert expired_count == 0
        assert len(scooped) == 0
    finally:
        db.close()
        if os.path.exists(db_path):
            os.unlink(db_path)


class FakeSecrets(dict):
    pass


class FakeAlertsDiscord:
    enabled = True


class FakeAlerts:
    discord = FakeAlertsDiscord()


class FakeConfig:
    def __init__(self):
        self.secrets = {}
        self.alerts = FakeAlerts()
        self.search = None


def test_scooped_deal_discord_message_builder_produces_sane_content():
    now = datetime.now(timezone.utc)
    listing = Listing(
        source="ebay", listing_id="x", title="MacBook Pro 14 M5 Max 128GB",
        price_usd=4500.0, url="https://ebay.com/itm/1",
        is_great_deal=True,
        first_seen_at=now - timedelta(hours=80),
        last_seen_at=now - timedelta(hours=76),
    )

    notifier = Notifier(FakeConfig())
    messages = notifier._build_scooped_deal_discord_messages([listing])

    assert len(messages) == 1
    embed = messages[0][0]
    assert "Scooped" in embed["title"]
    field = embed["fields"][0]
    assert "$4,500" in field["name"]
    assert "ebay" in field["name"]
    assert "MacBook Pro" in field["value"]
