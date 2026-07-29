# ───────────────────────────────────────────────────────────────────
# Tests for config loader
# ───────────────────────────────────────────────────────────────────

import os
import sys
import tempfile

# Add src to path so we can import our modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import yaml
from config import load_config, SearchConfig, PriceConfig


SAMPLE_CONFIG = """
search:
  product_name: "MacBook Pro"
  model_year: "2026"
  chip: "M5 Max"
  chip_fallback: "M5 Max"
  screen_size_inches: 14
  screen_size_fallback: ~
  ram_gb_primary: 128
  ram_gb_fallback: 64
  storage_gb_min: ~
  storage_gb_max: ~
  cpu_cores_min: 18
  gpu_cores_min: 40
  buy_it_now_only: true

price:
  absolute_max_usd: 8000
  great_deal_usd:
    128: 5000
    64: 4000
  good_deal_usd:
    128: 5500
    64: 4500
  top_deals_count: 25

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
    search_url: "https://www.bestbuy.com/site/searchpage.jsp?st={{query}}&af=condition%3Aopen+box"
  offerup:
    enabled: true
    search_url: "https://offerup.com/search/?q={{query}}"
  facebook:
    enabled: false
    search_url: ""

alerts:
  email:
    enabled: true
    smtp_server: "smtp.gmail.com"
    smtp_port: 587
  discord:
    enabled: true

schedule:
  cron: "0 */6 * * *"

database:
  url: "sqlite:///tmp/test_listings.db"
"""


def test_load_config():
    """Test that config.yaml parses correctly."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml",
                                     delete=False) as f:
        f.write(SAMPLE_CONFIG)
        tmp_path = f.name
    
    try:
        config = load_config(tmp_path)
        
        # Check search config
        assert config.search.product_name == "MacBook Pro"
        assert config.search.chip == "M5 Max"
        assert config.search.ram_gb_primary == 128
        assert config.search.ram_gb_fallback == 64
        assert config.search.screen_size_inches == 14
        assert config.search.cpu_cores_min == 18
        assert config.search.gpu_cores_min == 40
        
        # Check price config
        assert config.price.absolute_max_usd == 8000
        assert config.price.great_deal_usd[128] == 5000
        assert config.price.great_deal_usd[64] == 4000
        
        # Check site config
        assert config.sites.ebay.enabled is True
        assert config.sites.swappa.enabled is False
        assert config.sites.apple_refurb.enabled is True
        
        # Check schedule
        assert config.schedule["cron"] == "0 */6 * * *"
        
    finally:
        os.unlink(tmp_path)


def test_secrets_loading():
    """Test that environment variables are loaded as secrets."""
    os.environ["ALERT_EMAIL_FROM"] = "test@example.com"
    os.environ["DISCORD_WEBHOOK_URL"] = "https://discord.com/api/webhooks/test"
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml",
                                     delete=False) as f:
        f.write(SAMPLE_CONFIG)
        tmp_path = f.name
    
    try:
        config = load_config(tmp_path)
        assert config.secrets["email_from"] == "test@example.com"
        assert config.secrets["discord_webhook_url"] == \
            "https://discord.com/api/webhooks/test"
    finally:
        os.unlink(tmp_path)
        del os.environ["ALERT_EMAIL_FROM"]
        del os.environ["DISCORD_WEBHOOK_URL"]
