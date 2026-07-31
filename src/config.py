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
    chip: Optional[str]
    chip_fallback: Optional[str]
    screen_sizes: list[int]
    ram_gb_primary: Optional[int]
    ram_gb_fallback: Optional[int]
    storage_gb_min: Optional[int]
    storage_gb_max: Optional[int]
    cpu_cores_min: Optional[int]
    gpu_cores_min: Optional[int]
    results_per_size: int
    location: Optional[str]
    # ── Generation-window fields (set when a search opts into a
    # `generation_family` — see _expand_generation() below).  Left
    # at their defaults for manually-configured searches, which
    # keeps old-style single-chip config.yaml entries working as-is.
    chip_options: list[str] = field(default_factory=list)
    chip_generation_map: dict[str, int] = field(default_factory=dict)
    core_count_reference: dict[int, dict] = field(default_factory=dict)
    model_keywords: list[str] = field(default_factory=list)


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
    bestbuy: SiteConfig
    offerup: SiteConfig
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
        for search in config.searches:
            print(search.chip)
        print(config.price.absolute_max_usd)
    """
    searches: list[SearchConfig]
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


# ── Helper: expand a `generation_family` into concrete search criteria ──
# This is what makes searches.yaml entries future-proof.  Instead of
# hardcoding "M5 Max" / "iPhone 17 Pro Max" in config.yaml, a search
# entry can reference a family under `generations:` and get a rolling
# window of the last N flagship generations — bump one number
# (`current_gen`) per year, no other edits or code changes needed.
def _expand_generation(search_dict: dict, generations_raw: dict) -> dict:
    """
    If `search_dict` has a `generation_family` key, expand it into
    chip_options / chip_generation_map / core_count_reference (for
    chip-based products like MacBook Pro) or model_keywords (for
    model-number-based products like iPhone).

    Returns a shallow copy of search_dict with the expansion fields
    merged in.  If no `generation_family` is set, returns search_dict
    unchanged (manual single-chip config still works as before).
    """
    family_name = search_dict.get("generation_family")
    if not family_name:
        return search_dict

    family = generations_raw.get(family_name)
    if not family:
        raise ValueError(
            f"searches entry references generation_family "
            f"'{family_name}' but no such family exists under "
            f"'generations:' in config.yaml"
        )

    current_gen = family["current_gen"]
    lookback = family.get("lookback", 3)
    tier = family["tier"]
    generation_numbers = [current_gen - offset for offset in range(lookback)]

    expanded = dict(search_dict)

    if tier in ("Pro", "Max", "Ultra"):
        # Chip-based family (e.g. Mac "Max" chips) → M5 Max, M4 Max, M3 Max
        chip_options = [f"M{n} {tier}" for n in generation_numbers]
        expanded["chip_options"] = chip_options
        expanded["chip"] = chip_options[0]  # newest, for code that reads .chip directly (e.g. offerup.py)
        expanded["chip_generation_map"] = {
            f"M{n} {tier}": n for n in generation_numbers
        }
        raw_core_counts = family.get("core_counts", {})
        expanded["core_count_reference"] = {
            n: raw_core_counts[n] for n in generation_numbers if n in raw_core_counts
        }
    else:
        # Model-number-based family (e.g. "iPhone N Pro Max")
        product_prefix = search_dict["product_name"].split(" ")[0]  # e.g. "iPhone"
        expanded["model_keywords"] = [
            f"{product_prefix} {n} {tier}" for n in generation_numbers
        ]

    return expanded


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
    searches_raw    = raw["searches"]
    price_raw       = raw["price"]
    sites_raw       = raw["sites"]
    alerts_raw      = raw["alerts"]
    db_raw          = raw["database"]
    generations_raw = raw.get("generations", {})

    # Parse each search
    searches = []
    for s in searches_raw:
        s = _expand_generation(s, generations_raw)
        searches.append(SearchConfig(
            product_name=s["product_name"],
            chip=s.get("chip"),
            chip_fallback=s.get("chip_fallback"),
            screen_sizes=s.get("screen_sizes", []),
            ram_gb_primary=s.get("ram_gb_primary"),
            ram_gb_fallback=s.get("ram_gb_fallback"),
            storage_gb_min=s.get("storage_gb_min"),
            storage_gb_max=s.get("storage_gb_max"),
            cpu_cores_min=s.get("cpu_cores_min"),
            gpu_cores_min=s.get("gpu_cores_min"),
            results_per_size=s.get("results_per_size", 30),
            location=s.get("location"),
            chip_options=s.get("chip_options", []),
            chip_generation_map=s.get("chip_generation_map", {}),
            core_count_reference=s.get("core_count_reference", {}),
            model_keywords=s.get("model_keywords", []),
        ))
        if s.get("generation_family"):
            family_name = s["generation_family"]
            if "chip_options" in s:
                print(f"  [Config] {family_name} generations: {', '.join(s['chip_options'])}")
            elif "model_keywords" in s:
                print(f"  [Config] {family_name} generations: {', '.join(s['model_keywords'])}")

    # Build typed config
    config = Config(
        searches=searches,
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
            bestbuy=_parse_site(sites_raw["bestbuy"]),
            offerup=_parse_site(sites_raw["offerup"]),
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
