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

from environment import get_environment


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
        # Optional separate webhook for dev/staging test runs, so a
        # local run can post somewhere harmless instead of the real
        # production channel. See notifier.py's _send_discord() for
        # how this is used alongside is_production().
        "discord_webhook_url_dev": os.environ.get("DISCORD_WEBHOOK_URL_DEV"),
        # Facebook Marketplace requires a logged-in session to search at
        # all (unlike ebay/swappa/etc. which are public). There's no
        # username/password login flow implemented here — instead, the
        # site config expects a copied-out browser session cookie value.
        # See scrapers/facebook.py and docs/marketplace-setup.md.
        "facebook_session_cookie": os.environ.get("FACEBOOK_SESSION_COOKIE"),
    }


# ── Typed config classes ───────────────────────────────────────────
# Each class holds one section of config.yaml.
# Using `@dataclass` means Python auto-generates the __init__
# method — we don't have to write boilerplate.

@dataclass
class SearchConfig:
    """What we're looking for."""
    product_name: str
    chip: Optional[str]
    chip_fallback: Optional[str]
    screen_sizes: list[int]
    ram_gb_primary: Optional[int]
    ram_gb_fallback: Optional[int]
    storage_gb_min: Optional[int]
    storage_gb_max: Optional[int]
    results_per_size: int
    location: Optional[str]
    # ── Product type (see src/product_types/) ──────────────────
    # Which ProductTypeHandler owns matching/scoring for this search.
    # Defaults to "electronics" (MacBook Pro / iPhone — the only type
    # that exists today), so existing config.yaml entries need no
    # changes to keep working exactly as before. A future category
    # (e.g. "apparel") sets this to its own registered type name.
    product_type: str = "electronics"
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
    # Which product_type values this site can ever return results for.
    # None (the default) means "applies to every product type" — the
    # right default for general marketplaces (eBay, Swappa, Mercari,
    # OfferUp, BackMarket) that build queries from product_name alone.
    # Storefronts that only ever carry electronics (Apple Refurb,
    # BestBuy, Newegg, Gazelle) set this explicitly in config.yaml so
    # a future non-electronics search skips them instead of wasting a
    # request and returning zero every time.
    applicable_product_types: Optional[list[str]] = None
    # Craigslist-specific: the list of metro region slugs to search
    # (e.g. ["phoenix", "tucson", "losangeles"]) — Craigslist is
    # organized by city/metro, not by state, so a single state maps to
    # multiple region slugs and this needs to be a list, not a single
    # string, to "cast a wide net" across several states in one run.
    # None/empty (the default) means the scraper falls back to its own
    # DEFAULT_REGIONS (just Phoenix). Unused by every other site — see
    # scrapers/craigslist.py's module docstring for why this needs to
    # be config-driven rather than hardcoded, and for which region
    # slugs were verified live.
    regions: Optional[list[str]] = None


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
    newegg: SiteConfig
    gazelle: SiteConfig
    craigslist: SiteConfig
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


# ── Helper: keep dev/staging runs off the production database file ─
# WHY: config.yaml hardcodes one database URL (the production one,
# e.g. "sqlite:///data/listings.db") which GitHub Actions reads,
# writes to, and commits back to the repo on every scheduled run.
# If a local dev/staging run used that exact same URL, it would open
# the *same* SQLite file — and SQLite doesn't handle concurrent
# writers from separate processes gracefully. This exact problem
# happened in practice: a stray local process held the production DB
# file open, and the next GitHub Actions run failed with a "readonly
# database" error because the file was locked.
#
# The fix: whenever we're not in production, we rewrite the database
# URL to point at a sibling file (".dev.db" / ".staging.db" instead
# of ".db") so local test runs get their own on-disk database that
# can never collide with the one GitHub Actions maintains.
def _environment_scoped_db_url(url: str, environment: str) -> str:
    """
    Return a database URL scoped to the given environment.

    WHAT:
        In production, returns `url` unchanged. In dev or staging,
        inserts a ".dev" or ".staging" suffix before the file
        extension, so each environment gets its own database file
        on disk instead of sharing the production one.

    HOW:
        Splits `url` at the last "." (the extension separator) and
        rebuilds it with the environment name spliced in, e.g.:
            "sqlite:///data/listings.db" + "dev"
                -> "sqlite:///data/listings.dev.db"
        If `url` has no extension (no "." after the last "/"), the
        suffix is simply appended, so this never raises on unusual
        URLs — it degrades to "just add a suffix."

    WHY (see module-level comment above _environment_scoped_db_url):
        Prevents local/staging runs from ever opening the exact same
        SQLite file that the production GitHub Actions workflow
        reads and writes, which previously caused a "readonly
        database" error when a stray local process held the real
        production file locked.

    Args:
        url: The raw database URL from config.yaml (production URL).
        environment: One of "dev", "staging", "production" — usually
            the return value of environment.get_environment().

    Returns:
        The (possibly suffixed) database URL to actually use.
    """
    if environment == "production":
        return url

    # Split off everything after the last "/" so a "." in a directory
    # name (unlikely, but be safe) doesn't get treated as the
    # extension separator.
    last_slash = url.rfind("/")
    dir_part = url[: last_slash + 1]
    file_part = url[last_slash + 1 :]

    if "." in file_part:
        stem, _, ext = file_part.rpartition(".")
        scoped_file_part = f"{stem}.{environment}.{ext}"
    else:
        # No extension to split on — just append the suffix.
        scoped_file_part = f"{file_part}.{environment}"

    return f"{dir_part}{scoped_file_part}"


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
    # Which environment this run is executing in — "dev", "staging",
    # or "production". Defaulted via get_environment() (which itself
    # defaults to "production" when ENVIRONMENT is unset) so existing
    # callers that construct Config directly, or call load_config()
    # without touching this field, keep working unchanged.
    environment: str = field(default_factory=get_environment)
    # The SearchConfig currently being processed. main.py's per-search
    # loop sets this (`config.search = search_config`) before running
    # any scraper — every scraper and BaseScraper.passes_filters()/
    # parse_common_specs() reads config.search rather than taking a
    # SearchConfig parameter directly. Declared here (defaulting to
    # None) purely so that runtime contract is visible in the type
    # system instead of being an undeclared attribute nothing outside
    # main.py's loop could see was expected to exist.
    search: Optional["SearchConfig"] = None


# ── Helper: build a SiteConfig from raw YAML ──────────────────────
def _parse_site(raw: dict) -> SiteConfig:
    """Convert a raw YAML site entry into a typed SiteConfig."""
    return SiteConfig(
        enabled=raw.get("enabled", False),
        search_url=raw.get("search_url", ""),
        base_url=raw.get("base_url", ""),
        applicable_product_types=raw.get("applicable_product_types"),
        regions=raw.get("regions"),
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

    # Determine environment once, up front, so it can be used both to
    # scope the database URL below and to populate Config.environment.
    environment = get_environment()

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
            results_per_size=s.get("results_per_size", 30),
            location=s.get("location"),
            product_type=s.get("product_type", "electronics"),
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
            newegg=_parse_site(sites_raw["newegg"]),
            gazelle=_parse_site(sites_raw["gazelle"]),
            craigslist=_parse_site(sites_raw["craigslist"]),
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
        database=DatabaseConfig(
            url=_environment_scoped_db_url(db_raw["url"], environment)
        ),
        schedule=raw["schedule"],
        secrets=_load_env_secrets(),
        environment=environment,
    )

    return config
