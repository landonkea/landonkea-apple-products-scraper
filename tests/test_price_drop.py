# ───────────────────────────────────────────────────────────────────
# Tests for price-drop alerts
# ───────────────────────────────────────────────────────────────────
# A NEW alert type (separate from "new deal found"): when a listing
# we've already seen before drops in price on a later scrape. These
# tests cover:
#   1. A price drop below threshold does NOT alert.
#   2. A price drop above threshold DOES alert.
#   3. A price increase never alerts.
#   4. A first-time-seen listing (no prior price) never spuriously
#      triggers a "drop" alert.
#   5. listing_to_db() correctly hands back the prior price (or None
#      for a brand-new listing) so main.py can detect drops at all.
#   6. The Discord message builder produces sane, price-drop-specific
#      content.
# ───────────────────────────────────────────────────────────────────

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import PriceDropConfig, SearchConfig, AlertsConfig, EmailAlertConfig, DiscordAlertConfig
from database import Listing, get_session
from price_analyzer import is_meaningful_price_drop
from notifier import Notifier
from scrapers.base import ScrapedListing
import main as main_module


class FakeConfig:
    """Minimal stand-in for Config — only the attributes these
    functions actually touch are needed (same pattern used by
    tests/test_price_analyzer.py's FakeConfig)."""

    def __init__(self, price_drop: PriceDropConfig, search=None, alerts=None):
        self.price_drop = price_drop
        self.search = search
        self.alerts = alerts
        self.secrets = {}


def _drop_config(**overrides) -> PriceDropConfig:
    defaults = dict(enabled=True, min_drop_percent=5, min_drop_usd=50)
    defaults.update(overrides)
    return PriceDropConfig(**defaults)


# ── is_meaningful_price_drop() ─────────────────────────────────────

def test_drop_below_threshold_does_not_alert():
    """A drop that clears the dollar minimum but not the percent
    minimum (or vice versa) must NOT count as meaningful."""
    config = FakeConfig(_drop_config(min_drop_percent=5, min_drop_usd=50))

    # $40 off $1,000 = 4% -- under both the $50 and 5% bars.
    assert is_meaningful_price_drop(1000, 960, config) is False

    # $60 off $10,000 = 0.6% -- clears the $50 bar but not 5%.
    assert is_meaningful_price_drop(10000, 9940, config) is False


def test_drop_above_threshold_alerts():
    """A drop clearing BOTH the percent and dollar minimums must
    count as meaningful."""
    config = FakeConfig(_drop_config(min_drop_percent=5, min_drop_usd=50))

    # $300 off $5,000 = 6% -- clears both bars.
    assert is_meaningful_price_drop(5000, 4700, config) is True


def test_price_increase_never_alerts():
    """A price going UP (or staying flat) is never a "drop", no
    matter how large the increase."""
    config = FakeConfig(_drop_config())

    assert is_meaningful_price_drop(4000, 4500, config) is False
    assert is_meaningful_price_drop(4000, 4000, config) is False


def test_first_time_seen_listing_never_triggers_drop():
    """No prior price (old_price=None) means there's nothing to
    compare against -- must never spuriously alert."""
    config = FakeConfig(_drop_config())

    assert is_meaningful_price_drop(None, 3000, config) is False


def test_disabled_config_never_alerts():
    """config.price_drop.enabled=False must suppress alerts even for
    an otherwise-huge drop."""
    config = FakeConfig(_drop_config(enabled=False))

    assert is_meaningful_price_drop(5000, 1000, config) is False


# ── listing_to_db() prior-price bookkeeping ────────────────────────

def _scraped_listing(price_usd: float) -> ScrapedListing:
    return ScrapedListing(
        source="ebay",
        listing_id="drop_test_1",
        title='MacBook Pro 14" M5 Max 128GB',
        price_usd=price_usd,
        url="https://ebay.com/itm/drop_test_1",
        condition="Used",
        ram_gb=128,
        storage_gb=2048,
        screen_size=14.0,
        chip="M5 Max",
        location=None,
    )


class _FakeConfigForDb:
    """listing_to_db() only reads config.price.great_deal_usd."""

    class _Price:
        great_deal_usd = {128: 5000, 64: 4000}

    price = _Price()


def test_listing_to_db_first_insert_has_no_prior_price():
    db_path = tempfile.mktemp(suffix=".db")
    db_url = f"sqlite:///{db_path}"
    try:
        db = get_session(db_url)
        db_obj, old_price = main_module.listing_to_db(
            db, _scraped_listing(4500), _FakeConfigForDb()
        )
        assert old_price is None
        assert db_obj.price_usd == 4500
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_listing_to_db_reupsert_returns_prior_price():
    db_path = tempfile.mktemp(suffix=".db")
    db_url = f"sqlite:///{db_path}"
    try:
        db = get_session(db_url)
        main_module.listing_to_db(db, _scraped_listing(4500), _FakeConfigForDb())

        # Same source+listing_id, new (lower) price -- an upsert, not
        # an insert, so old_price must come back as the PREVIOUS price.
        db_obj, old_price = main_module.listing_to_db(
            db, _scraped_listing(4100), _FakeConfigForDb()
        )
        assert old_price == 4500
        assert db_obj.price_usd == 4100
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


# ── Notifier Discord message building ──────────────────────────────

def _make_notifier() -> Notifier:
    search = SearchConfig(
        product_name="MacBook Pro",
        chip="M5 Max",
        chip_fallback=None,
        screen_sizes=[14, 16],
        ram_gb_primary=128,
        ram_gb_fallback=64,
        storage_gb_min=1024,
        storage_gb_max=None,
        results_per_size=30,
        location=None,
    )
    alerts = AlertsConfig(
        email=EmailAlertConfig(enabled=False, smtp_server="", smtp_port=0),
        discord=DiscordAlertConfig(enabled=True),
    )
    config = FakeConfig(_drop_config(), search=search, alerts=alerts)
    return Notifier(config)


def test_price_drop_discord_message_contains_old_and_new_price():
    notifier = _make_notifier()
    listing = Listing(
        source="ebay",
        listing_id="drop_1",
        title='MacBook Pro 14" M5 Max 128GB',
        price_usd=4700.0,
        url="https://ebay.com/itm/drop_1?foo=bar",
        condition="Used",
    )

    messages = notifier._build_price_drop_discord_messages([(listing, 5000.0)])

    assert len(messages) == 1
    embeds = messages[0]
    assert len(embeds) == 1
    field = embeds[0]["fields"][0]
    assert "$5,000" in field["name"]
    assert "$4,700" in field["name"]
    assert "ebay.com/itm/drop_1" in field["value"]
    # URL should be cleaned of query params, same as the deal alerts.
    assert "foo=bar" not in field["value"]
    assert "Price Drop" in embeds[0]["title"]
