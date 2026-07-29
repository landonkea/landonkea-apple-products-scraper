# ───────────────────────────────────────────────────────────────────
# Configuration loader
# ───────────────────────────────────────────────────────────────────
# Reads config.yaml and makes every setting available as Python
# objects.  This way the rest of the code never worries about
# YAML parsing — it just asks `config.search.chip`.
# ───────────────────────────────────────────────────────────────────

import os
import yaml
from typing import Optional
from dataclasses import dataclass, field


# ── Helper: merge env vars into config ─────────────────────────────
# Some settings (passwords, webhook URLs) should NEVER be in
# config.yaml — they come from environment variables (GitHub Secrets).
def _load_env_secrets() -> dict:
    """
    Load alert credentials from environment variables.
    
    These are set in GitHub Secrets (or your local .env file).
    They NEVER get committed to the repo.
    """
    return {
        "email_from": os.environ.get("ALERT_EMAIL_FROM"),
        "email_to":   os.environ.get("ALERT_EMAIL_TO"),
        "gmail_app_password": os.environ.get("GMAIL_APP_PASSWORD"),
        "discord_webhook_url": os.environ.get("DISCORD_WEBHOOK_URL"),
    }


# ── Typed config classes ───────────────────────────────────────────
# Each class holds one section of config.yaml.
# Using `@dataclass` means Python auto-generates the __init__
# method — we don't have to write boilerplate.

@dataclass
class SearchConfig:
    """What hardware we're looking for."""
    product_name: str
    model_year: str
    chip: str
    chip_fallback: Optional[str]
    screen_size_inches: int
    screen_size_fallback: Optional[int]
    ram_gb_primary: int
    ram_gb_fallback: int
    storage_gb_min: Optional[int]
    storage_gb_max: Optional[int]
    cpu_cores_min: int
    gpu_cores_min: int
    buy_it_now_only: bool


@dataclass
class PriceConfig:
    """What counts as a good deal."""
    absolute_max_usd: float
    great_deal_usd: dict
    good_deal_usd: dict
    top_deals_count: int


@dataclass
class SiteConfig:
    """Settings for one marketplace site."""
    enabled: bool
    search_url: str = ""
    base_url: str = ""


@dataclass
class SitesConfig:
    """All marketplace sites."""
    ebay: SiteConfig
    swappa: SiteConfig
    apple_refurb: SiteConfig
    backmarket: SiteConfig
    mercari: SiteConfig
    facebook: SiteConfig


@dataclass
class EmailAlertConfig:
    """Email alert settings."""
    enabled: bool
    smtp_server: str
    smtp_port: int


@dataclass
class DiscordAlertConfig:
    """Discord alert settings."""
    enabled: bool


@dataclass
class AlertsConfig:
    """All alert channels."""
    email: EmailAlertConfig
    discord: DiscordAlertConfig


@dataclass
class DatabaseConfig:
    """Database connection info."""
    url: str


@dataclass
class Config:
    """
    Top-level config — holds everything.
    
    Usage:
        config = load_config()
        print(config.search.chip)           # "M5 Max"
        print(config.price.absolute_max_usd)  # 8000
    """
    search: SearchConfig
    price: PriceConfig
    sites: SitesConfig
    alerts: AlertsConfig
    database: DatabaseConfig
    schedule: dict
    secrets: dict = field(default_factory=_load_env_secrets)


# ── Helper: build a SiteConfig from raw YAML ──────────────────────
def _parse_site(raw: dict) -> SiteConfig:
    """Convert a raw YAML site entry into a typed SiteConfig."""
    return SiteConfig(
        enabled=raw.get("enabled", False),
        search_url=raw.get("search_url", ""),
        base_url=raw.get("base_url", ""),
    )


def load_config(path: str = "config.yaml") -> Config:
    """
    Read config.yaml and return a typed Config object.
    
    Args:
        path: Path to the YAML config file (default: "config.yaml").
    
    Returns:
        A Config dataclass with all settings.
    """
    with open(path, "r") as f:
        raw = yaml.safe_load(f)

    # Grab each section
    search_raw = raw["search"]
    price_raw  = raw["price"]
    sites_raw  = raw["sites"]
    alerts_raw = raw["alerts"]
    db_raw     = raw["database"]

    # Build typed config
    config = Config(
        search=SearchConfig(
            product_name=search_raw["product_name"],
            model_year=search_raw["model_year"],
            chip=search_raw["chip"],
            chip_fallback=search_raw.get("chip_fallback"),
            screen_size_inches=search_raw["screen_size_inches"],
            screen_size_fallback=search_raw.get("screen_size_fallback"),
            ram_gb_primary=search_raw["ram_gb_primary"],
            ram_gb_fallback=search_raw["ram_gb_fallback"],
            storage_gb_min=search_raw.get("storage_gb_min"),
            storage_gb_max=search_raw.get("storage_gb_max"),
            cpu_cores_min=search_raw["cpu_cores_min"],
            gpu_cores_min=search_raw["gpu_cores_min"],
            buy_it_now_only=search_raw["buy_it_now_only"],
        ),
        price=PriceConfig(
            absolute_max_usd=price_raw["absolute_max_usd"],
            great_deal_usd=price_raw["great_deal_usd"],
            good_deal_usd=price_raw["good_deal_usd"],
            top_deals_count=price_raw["top_deals_count"],
        ),
        sites=SitesConfig(
            ebay=_parse_site(sites_raw["ebay"]),
            swappa=_parse_site(sites_raw["swappa"]),
            apple_refurb=_parse_site(sites_raw["apple_refurb"]),
            backmarket=_parse_site(sites_raw["backmarket"]),
            mercari=_parse_site(sites_raw["mercari"]),
            facebook=_parse_site(sites_raw["facebook"]),
        ),
        alerts=AlertsConfig(
            email=EmailAlertConfig(
                enabled=alerts_raw["email"]["enabled"],
                smtp_server=alerts_raw["email"]["smtp_server"],
                smtp_port=alerts_raw["email"]["smtp_port"],
            ),
            discord=DiscordAlertConfig(
                enabled=alerts_raw["discord"]["enabled"],
            ),
        ),
        database=DatabaseConfig(url=db_raw["url"]),
        schedule=raw["schedule"],
        secrets=_load_env_secrets(),
    )

    return config
