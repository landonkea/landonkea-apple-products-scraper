# landonkea-apple-products-scraper

Scrapes eBay, Swappa, Apple Refurbished, Back Market, Mercari, Best Buy Open Box, Gazelle, Newegg, and Craigslist every 6 hours, alerting on great-priced deals for MacBook Pro (last 3 chip generations) and iPhone Pro Max (last 3 generations). OfferUp and Facebook Marketplace are wired in as login-gated stubs — they stay inert (zero network calls) until their session-cookie secrets are configured.

## How It Works

1. **Scheduled scraping** — runs every 6 hours via GitHub Actions cron (`.github/workflows/scrape.yml`), or manually via `workflow_dispatch`.
2. **Multi-site** — 10 scraper modules (`src/scrapers/`), each handling a different marketplace with its own anti-bot strategy (plain HTTP, Playwright + stealth, or discover-then-fetch for JSON-embedded pages).
3. **Pluggable product types** — matching/filtering/scoring logic isn't hardcoded to Apple hardware. `src/product_types/` defines a `ProductTypeHandler` interface; `electronics.py` is the first (and currently only) implementation. Adding a new category later (e.g. a different product line) means writing one new handler file, not touching every scraper.
4. **Price analysis** — `src/price_analyzer.py` scores listings against configured "great deal"/"good deal" thresholds, with a universal suspicious-price-outlier check plus product-type-specific bonuses delegated to the active handler.
5. **Alerts** — sends Discord webhook notifications (`src/notifier.py`) when a deal is found; production and non-production runs post to separate webhooks so test runs never spam the real channel.
6. **Deduplication & retention** — SQLite database (`src/database.py`) with upsert logic prevents duplicate alerts; listings inactive for 72h are soft-expired, and listings inactive for 180+ days are hard-deleted (`prune_old_inactive_listings`).
7. **Price-drop alerts** — a second, separate alert type from "new deal found": when a listing we've already seen before drops in price on a later scrape (e.g. a seller cuts $300 off an existing eBay listing), a dedicated Discord alert fires showing the old price, new price, and listing link. See [Price-Drop Alerts](#price-drop-alerts) below.

## Environments

This project has three real environments, controlled by `ENVIRONMENT` (`src/environment.py`, defaults to `production` if unset):

| Environment | How it runs | Database | Discord |
|---|---|---|---|
| `dev` | Local machine, manual runs | `data/listings.dev.db` (gitignored, never committed) | Dev webhook, or just logs if unset |
| `staging` | GitHub Actions, `staging` branch (`.github/workflows/scrape-staging.yml`) | `data/listings.staging.db` (committed to `staging` branch only) | Dev webhook |
| `production` | GitHub Actions, `main` branch, cron every 6h (`.github/workflows/scrape.yml`) | `data/listings.db` (committed to `main`) | Production webhook |

## Quick Start

```bash
# Install dependencies
pip install -e .

# Install Playwright browsers (needed for JS-heavy sites)
playwright install chromium

# Copy the env template and fill in your own values
cp .env.example .env

# Run once, locally, against the dev database
ENVIRONMENT=dev PYTHONPATH=src python3 -m main
```

## Configuration

Edit `config.yaml` to set:
- **`searches`** — list of products to search for (`product_name`, `product_type`, chip/generation window, screen sizes, RAM, etc.)
- **`price`** — deal thresholds (`absolute_max_usd`, `great_deal_usd` by RAM, `good_deal_usd`)
- **`price_drop`** — price-drop alert thresholds (`enabled`, `min_drop_percent`, `min_drop_usd`) — see [Price-Drop Alerts](#price-drop-alerts)
- **`sites`** — which marketplaces are enabled, and which `applicable_product_types` each one supports
- **`alerts`** — Discord toggle
- **`schedule`** — cron expression for GitHub Actions

## Price-Drop Alerts

Every alert described in "How It Works" above (the `price`/`great_deal_usd`/`good_deal_usd` thresholds) only ever fires when a listing is **first discovered**. Price-drop alerts are a separate mechanism layered on top: whenever a listing we've already seen on a prior scrape (same `source` + `listing_id`) shows up again at a **lower** price, that's a distinct signal worth its own alert — someone dropped their asking price on an item already in the database.

**How it works:**
1. `listing_to_db()` (`src/main.py`) captures a listing's price *before* the upsert overwrites it, so the prior price is never silently lost.
2. `is_meaningful_price_drop()` (`src/price_analyzer.py`) compares old vs. new price against the `price_drop` config thresholds.
3. If it qualifies, a dedicated "📉 Price Drop Alert" Discord message is sent (`Notifier.send_price_drop_alert()`), separate from and in addition to the regular deal alert for that run.

**Threshold design** (`config.yaml`'s `price_drop:` section):
```yaml
price_drop:
  enabled: true
  min_drop_percent: 5   # must drop by at least 5%...
  min_drop_usd: 50      # ...AND at least $50
```
A drop must clear **both** the percent and dollar minimum before it alerts — a percent-only rule fires on trivial drops for cheap items (5% of $60 is $3), and a dollar-only rule fires on trivial drops for expensive items ($50 off an $8,000 listing is 0.6%). Requiring both keeps alerts meaningful across the full price range these scrapers see, and prevents spam from tiny fluctuations (a seller nudging price by a few dollars).

A listing's **first** appearance never triggers a price-drop alert — there's no prior price to compare against.

## Environment Variables

See `.env.example` for the full list with descriptions. Locally these go in a `.env` file (gitignored); in GitHub Actions they're environment-scoped repository secrets — never committed.

## Scrapers

| Scraper | Site | Strategy |
|---|---|---|
| `ebay.py` | eBay | Plain HTTP requests + BeautifulSoup |
| `swappa.py` | Swappa | Product page → variant slugs → listing pages |
| `apple_refurb.py` | Apple Refurbished | Plain HTTP + HTML parsing |
| `backmarket.py` | Back Market | Discover generation links, then parse embedded Nuxt.js JSON for offer data |
| `mercari.py` | Mercari Japan | Playwright + fallback detail page scraping |
| `bestbuy.py` | Best Buy | Playwright for JS-rendered search results |
| `gazelle.py` | Gazelle | Plain HTTP + HTML parsing |
| `newegg.py` | Newegg | Plain HTTP + HTML parsing |
| `craigslist.py` | Craigslist | Plain HTTP + HTML parsing; config-driven list of metro regions (`sites.craigslist.regions`, defaults to `["phoenix"]`) — loops over every configured region (e.g. AZ/NM/CA/UT/NV/CO metros) to cover multiple states in one run |
| `offerup.py` | OfferUp | Playwright, login-gated stub |
| `facebook.py` | Facebook Marketplace | Login-gated stub, inert until `FACEBOOK_SESSION_COOKIE` is set |

## Project Structure

```
src/
├── config.py                # YAML config → typed dataclasses
├── database.py               # SQLAlchemy models + retention/pruning
├── environment.py            # dev/staging/production detection
├── main.py                   # Orchestrator: scrape → analyze → alert
├── notifier.py                # Discord alert dispatcher
├── price_analyzer.py         # Deal scoring algorithm
├── product_types/
│   ├── base.py                # ProductTypeHandler interface
│   └── electronics.py         # Apple hardware implementation
└── scrapers/
    ├── base.py                # BaseScraper ABC (rate limiting, dispatch to product_types)
    ├── ebay.py, swappa.py, apple_refurb.py, backmarket.py,
    ├── mercari.py, bestbuy.py, gazelle.py, newegg.py, craigslist.py,
    └── offerup.py, facebook.py
tests/
├── test_config.py, test_database.py, test_scrapers.py,
├── test_product_types.py, test_price_analyzer.py, test_environment.py,
├── test_price_drop.py, test_backmarket_scraper.py, test_gazelle_scraper.py,
└── test_newegg_scraper.py, test_craigslist_scraper.py
docs/
├── marketplace-setup.md       # how to configure login-gated marketplaces
└── marketplace-catalog.md     # researched reference of 34 candidate marketplaces
```

## Running Tests

```bash
pytest tests/ -v
ruff check .
mypy src/
```
