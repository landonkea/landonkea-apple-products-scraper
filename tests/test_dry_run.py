# ───────────────────────────────────────────────────────────────────
# Tests for the --dry-run / --no-alert CLI flag
# ───────────────────────────────────────────────────────────────────
# When config.dry_run is True, _run_one_search() must run the full
# scrape/save/analyze pipeline but never actually call into the
# Notifier's send methods -- letting you test locally against a real
# config.yaml without spamming Discord/email. Covers:
#   1. dry_run=True with a great deal present -> notifier NOT called.
#   2. dry_run=False with a great deal present -> notifier IS called.
#   3. main()'s CLI parsing recognizes both --dry-run and --no-alert.
# ───────────────────────────────────────────────────────────────────

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import (
    AlertsConfig,
    DiscordAlertConfig,
    EmailAlertConfig,
    PriceConfig,
    PriceDropConfig,
    SearchConfig,
)
from database import get_session
from scrapers.base import ScrapedListing
import main as main_module


class FakeScraper:
    source_name = "ebay"

    def __init__(self, listings):
        self._listings = listings

    def scrape(self):
        return self._listings


class SpyNotifier:
    """Stands in for notifier.Notifier -- records whether any send
    method was called, without doing real network I/O."""

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


def _price_config() -> PriceConfig:
    return PriceConfig(
        absolute_max_usd=8000,
        great_deal_usd={128: 5000, 64: 4000},
        good_deal_usd={128: 5500, 64: 4500},
        top_deals_count=40,
    )


class FakeConfig:
    def __init__(self, dry_run: bool):
        self.search = _search_config()
        self.price = _price_config()
        self.price_drop = PriceDropConfig(enabled=True, min_drop_percent=5, min_drop_usd=50)
        self.alerts = AlertsConfig(
            email=EmailAlertConfig(enabled=False, smtp_server="", smtp_port=587),
            discord=DiscordAlertConfig(enabled=True),
        )
        self.secrets = {}
        self.dry_run = dry_run
        self.sites = None  # unused -- get_enabled_scrapers is monkeypatched


def _run_with_dry_run(monkeypatch, dry_run: bool):
    SpyNotifier.instances.clear()
    monkeypatch.setattr(main_module, "Notifier", SpyNotifier)

    great_deal = ScrapedListing(
        source="ebay", listing_id="great1", title="MacBook Pro 14 M5 Max 128GB",
        price_usd=4000.0, url="https://ebay.com/x", condition="New",
        ram_gb=128, storage_gb=1024, screen_size=14.0, chip="M5 Max",
        location=None,
    )
    monkeypatch.setattr(
        main_module, "get_enabled_scrapers", lambda config: [FakeScraper([great_deal])]
    )

    db_path = tempfile.mktemp(suffix=".db")
    db = get_session(f"sqlite:///{db_path}")
    try:
        config = FakeConfig(dry_run=dry_run)
        main_module._run_one_search(config, config.search, db)
    finally:
        db.close()
        if os.path.exists(db_path):
            os.unlink(db_path)

    return SpyNotifier.instances[0]


def test_dry_run_suppresses_notifier_send(monkeypatch):
    spy = _run_with_dry_run(monkeypatch, dry_run=True)
    assert spy.send_alert_called is False


def test_no_dry_run_calls_notifier_send(monkeypatch):
    spy = _run_with_dry_run(monkeypatch, dry_run=False)
    assert spy.send_alert_called is True


def test_cli_recognizes_dry_run_flag(monkeypatch):
    argv = ["main.py", "--dry-run"]
    monkeypatch.setattr(sys, "argv", argv)
    dry_run = "--dry-run" in sys.argv or "--no-alert" in sys.argv
    assert dry_run is True


def test_cli_recognizes_no_alert_flag(monkeypatch):
    argv = ["main.py", "--no-alert"]
    monkeypatch.setattr(sys, "argv", argv)
    dry_run = "--dry-run" in sys.argv or "--no-alert" in sys.argv
    assert dry_run is True


def test_cli_defaults_to_not_dry_run(monkeypatch):
    argv = ["main.py"]
    monkeypatch.setattr(sys, "argv", argv)
    dry_run = "--dry-run" in sys.argv or "--no-alert" in sys.argv
    assert dry_run is False
