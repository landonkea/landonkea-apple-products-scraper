# ───────────────────────────────────────────────────────────────────
# Tests for the configuration loader (src/config.py)
# ───────────────────────────────────────────────────────────────────
# These tests verify that:
#   1. YAML config files parse correctly into typed dataclass objects.
#   2. SearchConfig, PriceConfig, SitesConfig, etc. all have the
#      expected values after parsing.
#   3. Environment variables are loaded as secrets.
#
# HOW TO RUN:
#   pytest tests/test_config.py -v
#   (from the project root directory)
# ───────────────────────────────────────────────────────────────────

import os
import sys
import tempfile

# Add src/ to the Python path so we can import the project's modules.
# This is needed because the tests live in tests/ and our code is in src/.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from config import load_config, _environment_scoped_db_url


# Sample YAML config that mimics the real config.yaml structure.
# The "searches" key is a LIST (plural), matching the actual config.py.
SAMPLE_CONFIG = """
# ── Searches (list of products to look for) ─────────────────────
searches:
  # MacBook Pro search configuration.
  - product_name: "MacBook Pro"
    chip: "M5 Max"
    chip_fallback: "M5 Max"
    screen_sizes: [14, 16]       # 14-inch and 16-inch models
    ram_gb_primary: 128           # Preferred RAM amount
    ram_gb_fallback: 64           # Fallback if 128GB isn't available
    storage_gb_min: ~             # No minimum storage requirement
    storage_gb_max: ~             # No maximum storage requirement
    results_per_size: 25          # Max listings per screen size
    location: ~                   # No location filter

# ── Price thresholds ────────────────────────────────────────────
price:
  absolute_max_usd: 8000           # Hard cap — ignore anything pricier
  great_deal_usd:                  # "Alert immediately!" thresholds
    128: 5000                      # 128GB RAM model: great deal under $5,000
    64: 4000                       # 64GB RAM model: great deal under $4,000
  good_deal_usd:                   # "Worth considering" thresholds
    128: 5500
    64: 4500
  top_deals_count: 25              # Show top 25 deals in the report

# ── Marketplace sites ───────────────────────────────────────────
sites:
  ebay:
    enabled: true
    search_url: "https://www.ebay.com/sch/i.html?_nkw={{query}}&LH_BIN=1"
  swappa:
    enabled: false
    base_url: "https://swappa.com/api"
  apple_refurb:
    enabled: true
    search_url: "https://www.apple.com/shop/refurbished/mac/2026-macbook-pro"
  backmarket:
    enabled: false
    search_url: "https://www.backmarket.com/search?q={{query}}"
  mercari:
    enabled: true
    search_url: "https://www.mercari.com/search/?keyword={{query}}"
  bestbuy:
    enabled: true
    search_url: "https://www.bestbuy.com/site/searchpage.jsp?st={{query}}"
  offerup:
    enabled: true
    search_url: "https://offerup.com/search/?q={{query}}"
  newegg:
    enabled: true
    search_url: "https://www.newegg.com/p/pl?d={{query}}"
  gazelle:
    enabled: true
    search_url: "https://buy.gazelle.com/search/suggest.json?q={{query}}&resources[type]=product"
  craigslist:
    enabled: true
    regions: ["phoenix", "tucson"]
    search_url: "https://www.craigslist.org/search/area/{{region}}?cat=sss&query={{query}}"
  facebook:
    enabled: false
    search_url: ""

# ── Alert channels ──────────────────────────────────────────────
alerts:
  email:
    enabled: true
    smtp_server: "smtp.gmail.com"
    smtp_port: 587
  discord:
    enabled: true

# ── Schedule ────────────────────────────────────────────────────
schedule:
  cron: "0 */6 * * *"              # Run every 6 hours

# ── Database ────────────────────────────────────────────────────
database:
  url: "sqlite:///tmp/test_listings.db"
"""


def test_load_config():
    """
    Test that a complete config.yaml parses correctly.

    VERIFIES:
    - All SearchConfig fields (product_name, chip, screen_sizes, etc.)
    - PriceConfig thresholds
    - Site enabled/disabled flags
    - Schedule cron expression
    """
    # Write the sample YAML to a temporary file (simulates real config.yaml).
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml",
                                     delete=False) as f:
        f.write(SAMPLE_CONFIG)
        tmp_path = f.name

    try:
        # Parse the YAML using the project's own config loader.
        config = load_config(tmp_path)

        # ── Verify SearchConfig values ──────────────────────────
        # The config.py defines `searches` as a list, so we check the first entry.
        search = config.searches[0]

        # Confirm the product name was parsed correctly.
        assert search.product_name == "MacBook Pro"
        # Confirm chip and fallback.
        assert search.chip == "M5 Max"
        assert search.chip_fallback == "M5 Max"
        # Confirm screen sizes (plural list, not singular integer).
        assert search.screen_sizes == [14, 16]
        # Confirm RAM preferences.
        assert search.ram_gb_primary == 128
        assert search.ram_gb_fallback == 64
        # Confirm results limit per screen size.
        assert search.results_per_size == 25

        # ── Verify PriceConfig values ───────────────────────────
        assert config.price.absolute_max_usd == 8000
        # Great deal thresholds by RAM amount.
        assert config.price.great_deal_usd[128] == 5000
        assert config.price.great_deal_usd[64] == 4000

        # ── Verify SiteConfig values ────────────────────────────
        # Some sites should be enabled, some disabled (matches SAMPLE_CONFIG).
        assert config.sites.ebay.enabled is True
        assert config.sites.swappa.enabled is False
        assert config.sites.apple_refurb.enabled is True
        # Craigslist's regions are config-driven (see config.py's
        # SiteConfig.regions and scrapers/craigslist.py) — confirm it
        # actually parses through from config.yaml.
        assert config.sites.craigslist.enabled is True
        assert config.sites.craigslist.regions == ["phoenix", "tucson"]
        # Sites that don't set `regions` in YAML should default to None
        # (the scraper itself falls back to ["phoenix"] — see
        # CraigslistScraper.DEFAULT_REGIONS), not raise a KeyError.
        assert config.sites.ebay.regions is None

        # ── Verify schedule ─────────────────────────────────────
        assert config.schedule["cron"] == "0 */6 * * *"

    finally:
        # Clean up: delete the temporary file.
        os.unlink(tmp_path)


def test_secrets_loading():
    """
    Test that environment variables are correctly loaded as secrets.

    The config loader reads ALERT_EMAIL_FROM and DISCORD_WEBHOOK_URL
    from environment variables (not from config.yaml).

    VERIFIES:
    - Secrets are populated from env vars
    - They end up in config.secrets dict
    """
    # Set environment variables as GitHub Secrets would.
    os.environ["ALERT_EMAIL_FROM"] = "test@example.com"
    os.environ["DISCORD_WEBHOOK_URL"] = "https://discord.com/api/webhooks/test"

    # Write and parse a minimal config.
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml",
                                     delete=False) as f:
        f.write(SAMPLE_CONFIG)
        tmp_path = f.name

    try:
        config = load_config(tmp_path)
        # Verify secrets loaded from env vars.
        assert config.secrets["email_from"] == "test@example.com"
        assert config.secrets["discord_webhook_url"] == \
            "https://discord.com/api/webhooks/test"
    finally:
        # Clean up the temp file and env vars.
        os.unlink(tmp_path)
        del os.environ["ALERT_EMAIL_FROM"]
        del os.environ["DISCORD_WEBHOOK_URL"]


def test_environment_scoped_db_url_production_unchanged():
    """
    In production, the database URL must be byte-for-byte unchanged.

    This is critical: GitHub Actions must keep reading/writing the
    exact same data/listings.db file it always has.
    """
    url = "sqlite:///data/listings.db"
    assert _environment_scoped_db_url(url, "production") == url


def test_environment_scoped_db_url_dev_and_staging_suffixed():
    """
    In dev/staging, a suffix is inserted before the file extension
    so local test runs never touch the production database file.
    """
    url = "sqlite:///data/listings.db"
    assert _environment_scoped_db_url(url, "dev") == \
        "sqlite:///data/listings.dev.db"
    assert _environment_scoped_db_url(url, "staging") == \
        "sqlite:///data/listings.staging.db"


def test_load_config_populates_environment_field():
    """
    Config.environment should reflect ENVIRONMENT, and the database
    URL should be scoped accordingly when not in production.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml",
                                     delete=False) as f:
        f.write(SAMPLE_CONFIG)
        tmp_path = f.name

    os.environ["ENVIRONMENT"] = "dev"
    try:
        config = load_config(tmp_path)
        assert config.environment == "dev"
        assert config.database.url == \
            "sqlite:///tmp/test_listings.dev.db"
    finally:
        os.unlink(tmp_path)
        del os.environ["ENVIRONMENT"]


def test_load_config_defaults_to_production_environment():
    """
    Without ENVIRONMENT set, load_config() must default to
    "production" and leave the database URL from config.yaml as-is.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml",
                                     delete=False) as f:
        f.write(SAMPLE_CONFIG)
        tmp_path = f.name

    os.environ.pop("ENVIRONMENT", None)
    try:
        config = load_config(tmp_path)
        assert config.environment == "production"
        assert config.database.url == "sqlite:///tmp/test_listings.db"
    finally:
        os.unlink(tmp_path)


def test_suspicious_price_thresholds_default_when_absent():
    """
    config.yaml written before suspicious_price_ratio/
    suspicious_min_sample existed (like SAMPLE_CONFIG, which omits
    them) must still load, falling back to the documented defaults
    (0.5 / 3) that used to be hardcoded module constants in
    price_analyzer.py.
    """
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml",
                                     delete=False) as f:
        f.write(SAMPLE_CONFIG)
        tmp_path = f.name

    try:
        config = load_config(tmp_path)
        assert config.price.suspicious_price_ratio == 0.5
        assert config.price.suspicious_min_sample == 3
    finally:
        os.unlink(tmp_path)


def test_suspicious_price_thresholds_are_config_driven():
    """
    Setting suspicious_price_ratio/suspicious_min_sample in
    config.yaml's price: block must override the defaults, the same
    way great_deal_usd/good_deal_usd already are.
    """
    custom_config = SAMPLE_CONFIG.replace(
        "top_deals_count: 25              # Show top 25 deals in the report",
        "top_deals_count: 25              # Show top 25 deals in the report\n"
        "  suspicious_price_ratio: 0.35\n"
        "  suspicious_min_sample: 5",
    )
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml",
                                     delete=False) as f:
        f.write(custom_config)
        tmp_path = f.name

    try:
        config = load_config(tmp_path)
        assert config.price.suspicious_price_ratio == 0.35
        assert config.price.suspicious_min_sample == 5
    finally:
        os.unlink(tmp_path)
