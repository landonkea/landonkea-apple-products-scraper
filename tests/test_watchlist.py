# ───────────────────────────────────────────────────────────────────
# Tests for the watchlist feature
# ───────────────────────────────────────────────────────────────────
# A FOURTH alert type: a user hand-tracks a specific listing (by URL)
# in data/watchlist.json and gets alerted whenever it's newly matched
# or its price changes, regardless of deal score. Covers:
#   1. load_watchlist()/save_watchlist() — missing file, non-list
#      JSON, and a real round-trip.
#   2. match_watchlist_entries() — matching by cleaned URL for a
#      brand-new entry, matching by (source, listing_id) once
#      resolved, and that a match backfills those fields in place.
#   3. find_watchlist_alerts() — first sighting alerts, an unchanged
#      price does NOT re-alert, and a price change (up OR down) DOES.
#   4. record_watchlist_alerts() — updates bookkeeping fields.
#   5. watchlist_path_for_environment() — production keeps the plain
#      path, dev/staging get their own scoped sibling file.
#   6. Notifier's watchlist Discord field/message builders.
#   7. main.py's actual wiring — _run_one_search() populates the
#      shared watchlist_matches accumulator from its own db_listings.
# ───────────────────────────────────────────────────────────────────

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from database import Listing, get_session
from notifier import Notifier
from scrapers.base import ScrapedListing
from config import (
    AlertsConfig,
    DiscordAlertConfig,
    EmailAlertConfig,
    PriceConfig,
    PriceDropConfig,
    SearchConfig,
)
import main as main_module
from watchlist import (
    load_watchlist,
    save_watchlist,
    match_watchlist_entries,
    find_watchlist_alerts,
    record_watchlist_alerts,
    watchlist_path_for_environment,
)


# ── load_watchlist() / save_watchlist() ────────────────────────────

def test_load_watchlist_missing_file_returns_empty_list():
    path = tempfile.mktemp(suffix=".json")
    assert load_watchlist(path) == []


def test_load_watchlist_non_list_json_returns_empty_list():
    path = tempfile.mktemp(suffix=".json")
    with open(path, "w") as f:
        f.write('{"not": "a list"}')
    try:
        assert load_watchlist(path) == []
    finally:
        os.unlink(path)


def test_save_and_load_watchlist_roundtrip():
    tmpdir = tempfile.mkdtemp()
    path = os.path.join(tmpdir, "nested", "watchlist.json")
    entries = [{"url": "https://www.ebay.com/itm/123456789", "note": "must buy under $3500"}]

    save_watchlist(entries, path)
    loaded = load_watchlist(path)

    assert loaded == entries
    assert os.path.exists(path)


# ── match_watchlist_entries() ──────────────────────────────────────

def _make_listing(**overrides):
    defaults = dict(
        source="ebay",
        listing_id="123456789",
        title="MacBook Pro 14 M5 Max 128GB",
        price_usd=3800.0,
        url="https://www.ebay.com/itm/123456789?hash=abc",
    )
    defaults.update(overrides)
    return Listing(**defaults)


def test_match_by_cleaned_url_for_unresolved_entry():
    entry = {"url": "https://www.ebay.com/itm/123456789"}
    listing = _make_listing()

    matches = match_watchlist_entries([entry], [listing])

    assert len(matches) == 1
    assert matches[0] == (entry, listing)


def test_match_backfills_source_and_listing_id_in_place():
    entry = {"url": "https://www.ebay.com/itm/123456789"}
    listing = _make_listing()

    match_watchlist_entries([entry], [listing])

    assert entry["source"] == "ebay"
    assert entry["listing_id"] == "123456789"


def test_match_by_resolved_source_and_listing_id_even_if_url_changed():
    # Once resolved, matching no longer depends on the URL staying
    # byte-for-byte identical -- a listing's URL can pick up new
    # tracking params between scrapes.
    entry = {
        "url": "https://www.ebay.com/itm/123456789?old=params",
        "source": "ebay",
        "listing_id": "123456789",
    }
    listing = _make_listing(url="https://www.ebay.com/itm/123456789?totally=different")

    matches = match_watchlist_entries([entry], [listing])

    assert len(matches) == 1


def test_no_match_returns_empty():
    entry = {"url": "https://www.ebay.com/itm/999"}
    listing = _make_listing()

    matches = match_watchlist_entries([entry], [listing])

    assert matches == []


# ── find_watchlist_alerts() ────────────────────────────────────────

def test_first_sighting_is_alert_worthy():
    entry = {"url": "https://www.ebay.com/itm/123456789"}
    listing = _make_listing(price_usd=3800.0)

    alerts = find_watchlist_alerts([(entry, listing)])

    assert alerts == [(entry, listing)]


def test_unchanged_price_does_not_alert():
    entry = {"url": "https://www.ebay.com/itm/123456789", "last_alerted_price": 3800.0}
    listing = _make_listing(price_usd=3800.0)

    alerts = find_watchlist_alerts([(entry, listing)])

    assert alerts == []


def test_price_drop_alerts():
    entry = {"url": "https://www.ebay.com/itm/123456789", "last_alerted_price": 3800.0}
    listing = _make_listing(price_usd=3500.0)

    alerts = find_watchlist_alerts([(entry, listing)])

    assert alerts == [(entry, listing)]


def test_price_increase_also_alerts():
    # Unlike price-drop alerts, a watched listing going UP is just as
    # relevant to a buy-now-or-wait decision.
    entry = {"url": "https://www.ebay.com/itm/123456789", "last_alerted_price": 3500.0}
    listing = _make_listing(price_usd=3800.0)

    alerts = find_watchlist_alerts([(entry, listing)])

    assert alerts == [(entry, listing)]


# ── record_watchlist_alerts() ──────────────────────────────────────

def test_record_watchlist_alerts_updates_entry_in_place():
    entry = {"url": "https://www.ebay.com/itm/123456789"}
    listing = _make_listing(price_usd=3800.0)

    record_watchlist_alerts([(entry, listing)])

    assert entry["last_alerted_price"] == 3800.0
    assert "last_alerted_at" in entry


# ── watchlist_path_for_environment() ───────────────────────────────

def test_production_uses_plain_path():
    assert watchlist_path_for_environment("production") == "data/watchlist.json"


def test_dev_and_staging_get_scoped_sibling_files():
    assert watchlist_path_for_environment("dev") == "data/watchlist.dev.json"
    assert watchlist_path_for_environment("staging") == "data/watchlist.staging.json"


# ── Notifier watchlist Discord builders ────────────────────────────

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


def test_watchlist_field_shows_first_sighting_without_arrow():
    entry = {"url": "https://www.ebay.com/itm/123456789", "note": "must buy under $3500"}
    listing = _make_listing(price_usd=3800.0)

    notifier = Notifier(FakeConfig())
    field = notifier._build_watchlist_field(entry, listing)

    assert "$3,800" in field["name"]
    assert "→" not in field["name"]
    assert "must buy under $3500" in field["value"]


def test_watchlist_field_shows_price_change_with_arrow():
    entry = {"url": "https://www.ebay.com/itm/123456789", "last_alerted_price": 3800.0}
    listing = _make_listing(price_usd=3500.0)

    notifier = Notifier(FakeConfig())
    field = notifier._build_watchlist_field(entry, listing)

    assert "$3,800 → $3,500" in field["name"]


def test_watchlist_discord_messages_produce_sane_content():
    entry = {"url": "https://www.ebay.com/itm/123456789"}
    listing = _make_listing(price_usd=3800.0)

    notifier = Notifier(FakeConfig())
    messages = notifier._build_watchlist_discord_messages([(entry, listing)])

    assert len(messages) == 1
    embed = messages[0][0]
    assert "Watchlist" in embed["title"]
    field = embed["fields"][0]
    assert "ebay" in field["name"]
    assert "MacBook Pro" in field["value"]


def test_send_watchlist_alert_noop_for_empty_matches():
    # Should never even try to build/post a message for an empty
    # batch -- mirrors send_scooped_deal_alert/send_price_drop_alert.
    notifier = Notifier(FakeConfig())
    notifier.send_watchlist_alert([])  # must not raise


# ── main.py wiring: _run_one_search() populates the accumulator ────

class FakeScraper:
    source_name = "ebay"

    def __init__(self, listings):
        self._listings = listings

    def scrape(self):
        return self._listings


class SpyNotifier:
    instances = []

    def __init__(self, config):
        self.config = config
        self.send_alert_called = False
        self.send_price_drop_alert_called = False
        SpyNotifier.instances.append(self)

    def send_alert(self, top_deals, stats):
        self.send_alert_called = True

    def send_price_drop_alert(self, price_drops):
        self.send_price_drop_alert_called = True


def _search_config() -> SearchConfig:
    return SearchConfig(
        product_name="MacBook Pro",
        chip=None,
        chip_fallback=None,
        screen_sizes=[],
        ram_gb_primary=128,
        ram_gb_fallback=64,
        storage_gb_min=1024,
        storage_gb_max=None,
        results_per_size=30,
        location=None,
    )


class FakeRunConfig:
    def __init__(self):
        self.search = _search_config()
        self.price = PriceConfig(
            absolute_max_usd=8000,
            great_deal_usd={128: 5000, 64: 4000},
            good_deal_usd={128: 5500, 64: 4500},
            top_deals_count=40,
        )
        self.price_drop = PriceDropConfig(enabled=True, min_drop_percent=5, min_drop_usd=50)
        self.alerts = AlertsConfig(
            email=EmailAlertConfig(enabled=False, smtp_server="", smtp_port=587),
            discord=DiscordAlertConfig(enabled=True),
        )
        self.secrets = {}
        self.dry_run = False
        self.sites = None  # unused -- get_enabled_scrapers is monkeypatched


def test_run_one_search_populates_watchlist_matches_accumulator(monkeypatch):
    SpyNotifier.instances.clear()
    monkeypatch.setattr(main_module, "Notifier", SpyNotifier)

    tracked = ScrapedListing(
        source="ebay", listing_id="watched1", title="MacBook Pro 14 M5 Max 128GB",
        price_usd=4200.0, url="https://www.ebay.com/itm/watched1", condition="Used",
        ram_gb=128, storage_gb=1024, screen_size=14.0, chip="M5 Max",
        location=None,
    )
    monkeypatch.setattr(
        main_module, "get_enabled_scrapers", lambda config: [FakeScraper([tracked])]
    )

    db_path = tempfile.mktemp(suffix=".db")
    db = get_session(f"sqlite:///{db_path}")
    try:
        config = FakeRunConfig()
        watchlist_entries = [{"url": "https://www.ebay.com/itm/watched1"}]
        watchlist_matches: list = []

        main_module._run_one_search(
            config, config.search, db, watchlist_entries, watchlist_matches
        )

        assert len(watchlist_matches) == 1
        matched_entry, matched_listing = watchlist_matches[0]
        assert matched_entry is watchlist_entries[0]
        assert matched_listing.listing_id == "watched1"
        assert matched_listing.price_usd == 4200.0
        # The entry should have been resolved to a stable match key.
        assert matched_entry["source"] == "ebay"
        assert matched_entry["listing_id"] == "watched1"
    finally:
        db.close()
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_run_one_search_with_no_watchlist_entries_is_a_noop(monkeypatch):
    # Default args (no watchlist passed at all) must still work --
    # existing callers/tests that don't care about the watchlist
    # shouldn't be forced to thread it through.
    SpyNotifier.instances.clear()
    monkeypatch.setattr(main_module, "Notifier", SpyNotifier)

    listing = ScrapedListing(
        source="ebay", listing_id="plain1", title="MacBook Pro 14 M5 Max 128GB",
        price_usd=4200.0, url="https://www.ebay.com/itm/plain1", condition="Used",
        ram_gb=128, storage_gb=1024, screen_size=14.0, chip="M5 Max",
        location=None,
    )
    monkeypatch.setattr(
        main_module, "get_enabled_scrapers", lambda config: [FakeScraper([listing])]
    )

    db_path = tempfile.mktemp(suffix=".db")
    db = get_session(f"sqlite:///{db_path}")
    try:
        config = FakeRunConfig()
        # No watchlist_entries/watchlist_matches passed at all.
        main_module._run_one_search(config, config.search, db)
    finally:
        db.close()
        if os.path.exists(db_path):
            os.unlink(db_path)
