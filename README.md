# landonkea-apple-products-scraper

Scrapes eBay, Swappa, Apple Refurbished, Back Market, Mercari, Best Buy Open Box, Gazelle, Newegg, and Craigslist every 6 hours, alerting on great-priced deals for MacBook Pro (last 3 chip generations) and iPhone Pro Max (last 3 generations). OfferUp and Facebook Marketplace are wired in as login-gated stubs — they stay inert (zero network calls) until their session-cookie secrets are configured.

## How It Works

1. **Scheduled scraping** — runs every 6 hours via GitHub Actions cron (`.github/workflows/scrape.yml`), or manually via `workflow_dispatch`.
2. **Multi-site** — 10 scraper modules (`src/scrapers/`), each handling a different marketplace with its own anti-bot strategy (plain HTTP, Playwright + stealth, or discover-then-fetch for JSON-embedded pages).
3. **Pluggable product types** — matching/filtering/scoring logic isn't hardcoded to Apple hardware. `src/product_types/` defines a `ProductTypeHandler` interface; `electronics.py` is the reference implementation (MacBook Pro/iPhone). `apparel.py` is a second, structurally different implementation (boots — size/brand/color instead of chip/RAM/storage) proving the interface actually generalizes; it's registered but not wired into any live `searches:` entry in `config.yaml` (see the commented-out example there), so it has zero effect on production alerts. Adding a real new category means writing one new handler file plus a `searches:` entry, not touching every scraper.
4. **Price analysis** — `src/price_analyzer.py` scores listings against configured "great deal"/"good deal" thresholds, with a universal suspicious-price-outlier check plus product-type-specific bonuses delegated to the active handler.
5. **Alerts** — sends Discord webhook notifications (`src/notifier.py`) when a deal is found; production and non-production runs post to separate webhooks so test runs never spam the real channel.
6. **Deduplication & retention** — SQLite database (`src/database.py`) with upsert logic prevents duplicate alerts; listings inactive for 72h are soft-expired, and listings inactive for 180+ days are hard-deleted (`prune_old_inactive_listings`, which also cleans up their price history).
7. **Price-drop alerts** — a second, separate alert type from "new deal found": when a listing we've already seen before drops in price on a later scrape (e.g. a seller cuts $300 off an existing eBay listing), a dedicated Discord alert fires showing the old price, new price, and listing link. See [Price-Drop Alerts](#price-drop-alerts) below.
8. **Per-listing price history** — every price a specific listing has ever been seen at (not just daily aggregates) is recorded in a `price_history` table, one row per price *change* (not per scrape). See [Price History](#price-history) below.
9. **Scooped-deal alerts** — a great deal that goes inactive within 24h of first being seen is very likely sold, and gets a dedicated "🏃 Scooped!" Discord alert. See [Scooped Deal Alerts](#scooped-deal-alerts) below.

## Environments

This project has three real environments, controlled by `ENVIRONMENT` (`src/environment.py`, defaults to `production` if unset):

| Environment | How it runs | Database | Discord |
|---|---|---|---|
| `dev` | Local machine, manual runs | `data/listings.dev.db` (gitignored, never committed) | Dev webhook, or just logs if unset |
| `staging` | GitHub Actions, `staging` branch (`.github/workflows/scrape-staging.yml`) | `data/listings.staging.db` (committed to `staging` branch only) | Dev webhook |
| `production` | GitHub Actions, `main` branch, cron every 6h (`.github/workflows/scrape.yml`) | `data/listings.db` (committed to `main`) | Production webhook |

The [watchlist](#watchlist) file is scoped the same way: `data/watchlist.dev.json` / `data/watchlist.staging.json` (both gitignored) vs. `data/watchlist.json` (committed to `main`).

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

# Run locally without sending any real Discord/email alerts
# (--dry-run and --no-alert are synonyms) -- still scrapes, saves to
# the database, and prints its normal summary, just never posts.
ENVIRONMENT=dev PYTHONPATH=src python3 -m main --dry-run
```

## Running with Docker

An alternative way to run the scraper — for local dev, or for
self-hosting somewhere that isn't GitHub Actions. **This is
additive, not a replacement**: the primary production runtime is
still the GitHub Actions cron workflow (`.github/workflows/scrape.yml`),
running every 6 hours exactly as described above. Nothing about that
workflow changes because a Docker image also exists.

The image installs this project's dependencies plus Playwright's
Chromium binary (`playwright install --with-deps chromium`) — needed
because several scrapers (eBay, Best Buy, OfferUp, Mercari, Back
Market, Facebook) render pages with a real headless browser rather
than plain HTTP requests. The rest of the scrapers (Swappa, Apple
Refurb, Gazelle, Newegg, Craigslist) use plain `requests`/BeautifulSoup
and don't need it, but all scrapers share one process/image.

### docker compose (recommended for local dev)

```bash
cp .env.example .env     # fill in your own values, or leave blank —
                          # ENVIRONMENT defaults to dev, which just
                          # logs alerts instead of posting them

docker compose run --rm scraper                # full scrape pass
docker compose run --rm scraper --dry-run      # scrape, never alert
docker compose build                            # rebuild after a dependency change
```

`docker-compose.yml` mounts `./data` into the container (so
`data/listings.dev.db` and `data/watchlist.dev.json` persist across
runs on the host instead of disappearing when the container exits)
and mounts `./config.yaml` read-only (so you can tweak searches/
thresholds without rebuilding the image). It also sets
`shm_size: 1gb` — Docker's 64MB default `/dev/shm` is too small for
headless Chromium and causes intermittent "Page crashed" errors from
the Playwright-driven scrapers.

### Plain `docker run`

```bash
docker build -t apple-product-scraper .

docker run --rm \
  --shm-size=1g \
  -e ENVIRONMENT=dev \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/config.yaml:/app/config.yaml:ro" \
  --env-file .env \
  apple-product-scraper --dry-run
```

`--shm-size=1g` matters here too, for the same Chromium reason as
above — a plain `docker run` without it doesn't get Docker Compose's
`shm_size` setting for free.

### CI

`.github/workflows/docker-build.yml` builds the image and runs a real
`--dry-run` scrape pass inside it on every push/PR to `main`/`staging`,
as a smoke test that the Dockerfile and Playwright-in-a-container setup
still work — separate from, and without touching, the production
`scrape.yml`/`scrape-staging.yml` cron workflows.

## Configuration

Edit `config.yaml` to set:
- **`searches`** — list of products to search for (`product_name`, `product_type`, chip/generation window, screen sizes, RAM, etc.)
- **`price`** — deal thresholds (`absolute_max_usd`, `great_deal_usd` by RAM, `good_deal_usd`, `top_deals_count`, the suspicious-price-outlier safeguard's `suspicious_price_ratio`/`suspicious_min_sample`, and an optional `source_reliability` dict overriding/adding to `price_analyzer.py`'s built-in per-marketplace trust bonuses)
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

## Price History

`DailyPriceStat` (used for the trend charts on the GitHub Pages site) only ever tracks a *daily aggregate* per product generation — it can't answer "what has this exact listing's price done over time?" The `price_history` table (`src/database.py`'s `PriceHistory` model) fills that gap: one row per `(listing_id, price_usd, recorded_at)`, written by `record_price_history()` alongside the existing upsert in `listing_to_db()`.

To keep the table meaningful (and bounded), a new row is only written when a listing is seen for the **first** time, or its price **changes** from the last recorded point — a listing whose price never moves doesn't accumulate a near-duplicate row every 6-hour scrape. `prune_old_inactive_listings()` deletes a listing's price-history rows along with it once it's been inactive for 180+ days, so history never outlives its listing.

## Scooped Deal Alerts

A third alert type: when a listing flagged `is_great_deal` goes inactive (see `expire_stale_listings` — no longer seen in a scrape for 72+ hours) within 24 hours of first being found, it's very likely someone else bought it, not just a stale/removed listing. That combination — genuinely good price, gone fast — is a signal worth its own Discord alert (`Notifier.send_scooped_deal_alert()`), separate from and in addition to the regular deal/price-drop alerts. It's confirmation the scoring is finding real deals, and a data point for how fast to act next time.

## Watchlist

A fourth alert type, and the only one driven by a human decision rather than the scraper's own scoring: track one specific listing (found by hand — e.g. an eBay auction with unusual RAM/storage that would never match a configured search) and get alerted whenever it's seen again or its price changes, regardless of deal score.

**How it works:**
1. Add an entry to `data/watchlist.json` (`data/watchlist.dev.json` locally — see [Environments](#environments)):
   ```json
   [
     { "url": "https://www.ebay.com/itm/123456789", "note": "must buy under $3500" }
   ]
   ```
   Only `url` is required; `note` is optional free text shown in the alert.
2. Every run, `match_watchlist_entries()` (`src/watchlist.py`) cross-references every entry against that run's freshly scraped listings (by `source`+`listing_id` once resolved, falling back to a cleaned-URL match for a brand-new entry).
3. `find_watchlist_alerts()` narrows matches down to ones actually worth alerting on: first sighting, or a price change (up **or** down — unlike price-drop alerts, a watched listing's price rising is just as relevant to a buy-now-or-wait decision) since the last alert.
4. A dedicated "🔭 Watchlist Alert" Discord message fires (`Notifier.send_watchlist_alert()`), and the entry's `last_alerted_price`/`last_alerted_at` are updated so an unchanged price doesn't re-alert every 6-hour run.

An entry with no match in a given run (not currently listed, sold, or a marketplace's scraper hit an error) is simply skipped — not an error.

## Score Transparency & Apple Refurb Baseline

Every listing's `deal_score` is now backed by a `deal_score_breakdown` — named components (`base`, `price_vs_median`, `condition`, `source_reliability`, `spec_bonus`, plus a `clamp_adjustment`/`suspicious_price_cap` when applicable) that sum to the final score, rendered as a compact one-line string (`format_score_breakdown()` in `src/price_analyzer.py`, e.g. `base 50 | price +18.2 | condition +5 | source +2 | specs +10`) under each listing in a Discord deal alert — no more re-deriving "why did this score 72?" by hand.

Two of those components are new:
- **`source_reliability`** — a small per-marketplace trust nudge (Apple Refurb/BackMarket +2, Swappa/Gazelle/BestBuy/Newegg +1, eBay 0, Mercari/Facebook -1, Craigslist/OfferUp -3), tunable via `config.yaml`'s `price.source_reliability`. It's a nudge, not a gate — a great price on Craigslist can still outscore a mediocre price on Apple Refurb.
- **"vs. Apple's own price"** — whenever Apple Refurb is carrying the exact same configuration (`chip`, `ram_gb`, `storage_gb`) as another listing in the same batch, and that listing is cheaper, the alert shows e.g. "🍎 42% below Apple's refurb price ($3,199)" (`PriceAnalyzer._compute_apple_refurb_baselines()`).

Both `deal_score_breakdown` and the Apple-refurb comparison fields are runtime-only attributes on `Listing` (not database columns) — cheap to recompute every run from data already in the current batch, so there's no schema migration and nothing to go stale.

## Second Product Type: Apparel (Architecture Proof)

`src/product_types/apparel.py` is a second, real `ProductTypeHandler` implementation — boots, not Apple hardware. It exists to prove the pluggable product-type architecture (`src/product_types/base.py`) actually generalizes to a category with a completely different field set, not just different constants plugged into the electronics shape:

| | electronics.py | apparel.py |
|---|---|---|
| Parsed spec fields | `ram_gb`, `storage_gb`, `screen_size`, `chip`, `cpu_cores`, `gpu_cores` | `size`, `brand`, `color` |
| Relevance filter | accessory/broken/locked keyword lists | accessory (laces/shoe trees/polish) + bad-condition keyword lists |
| Scoring bonuses | RAM tier, chip generation, core counts, screen size, storage | preferred brand, exact size match, new/deadstock condition, color preference |
| Price floor | $200 (Mac) / $100 (iPhone) | $50 |

What this required beyond the handler itself:
- `ScrapedListing` and the `listings` DB table gained three new optional columns (`size`, `brand`, `color`, covered by Alembic's baseline migration — see `migrations/versions/0001_baseline_schema.py` and the "Database migrations" section below) — always `NULL`/`None` for electronics listings, only populated for an apparel search. Proves a single `listings` table can carry more than one category's specs, not just one handler swapped for another.
- `SearchConfig` gained `sizes`, `preferred_brands`, `colors` (all optional, default empty — every existing `config.yaml` entry keeps working unchanged).
- **Zero changes** to any of the 10 scraper files — `get_enabled_scrapers()` automatically includes the general marketplaces (eBay, Swappa, Mercari, OfferUp, BackMarket, Craigslist, Facebook — they build queries from `product_name` alone) and automatically skips the Apple-only storefronts (Apple Refurb, BestBuy, Newegg, Gazelle, already marked `applicable_product_types: [electronics]`), exactly as `product_types/base.py`'s "how to add a new product type" doc comment predicted.

**Not enabled in production**: `apparel` is registered in `PRODUCT_TYPES` but there's no active `searches:` entry for it in `config.yaml` — only a commented-out example. This repo's owner wants their Discord channel alerting on Apple deals, not boots, so the feature is proven via `tests/test_product_types_apparel.py` (28 tests: parsing, filtering, scoring, and a `get_enabled_scrapers()` integration check) rather than by actually running it in production. Uncomment the example in `config.yaml` to turn it on for real.

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

## Database Migrations

Schema changes are managed with [Alembic](https://alembic.sqlalchemy.org/), not manual `ALTER TABLE`s. Migrations live in `migrations/versions/` and run automatically — `src/database.py`'s `get_session()` calls `run_migrations()` (Alembic's `upgrade head`, invoked programmatically) every time the scraper starts, before any read/write happens. This means:

- A fresh, empty database gets every table created from scratch.
- An existing database (dev/staging/production) only has whatever's actually missing applied — already-current databases are a no-op.
- There's nothing to remember to run manually — `python -m main` (locally, in Docker, or in CI) always leaves the database at the latest schema first.

`migrations/versions/0001_baseline_schema.py` is the starting point: it reproduces exactly what this project's schema looked like right before Alembic was introduced (previously kept current by a hand-rolled `_ensure_columns()` ALTER-TABLE stopgap in `database.py`, now removed). It's written to be safe to run against a brand-new database, an already-fully-migrated one, or an old database still missing a few of the newer optional columns (`cpu_cores`/`gpu_cores`/`size`/`brand`/`color`) — see that file's docstring for why it guards every operation instead of calling `create_table`/`add_column` unconditionally.

**Adding a new migration** (once there's an actual schema change to make): update the model in `src/database.py`, then generate a revision with

```bash
alembic revision --autogenerate -m "add some_column to listings"
```

Review the generated file in `migrations/versions/` before committing — autogenerate is a good first draft, not a guarantee (it can miss things like index/constraint renames). It'll be picked up automatically on the next `get_session()` call; no other wiring needed.

**Manual/ops use** (inspecting or fixing a database by hand, outside a scraper run): the bare `alembic` CLI works too, e.g. `alembic upgrade head` or `alembic current`, using the default URL in `alembic.ini` (production's `data/listings.db`) unless overridden.

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
│   ├── electronics.py         # Apple hardware implementation (MacBook Pro/iPhone)
│   └── apparel.py             # Boots implementation — second category, not live in config.yaml
└── scrapers/
    ├── base.py                # BaseScraper ABC (rate limiting, dispatch to product_types)
    ├── ebay.py, swappa.py, apple_refurb.py, backmarket.py,
    ├── mercari.py, bestbuy.py, gazelle.py, newegg.py, craigslist.py,
    └── offerup.py, facebook.py
tests/
├── test_config.py, test_database.py, test_scrapers.py,
├── test_product_types.py, test_product_types_apparel.py, test_price_analyzer.py, test_environment.py,
├── test_price_drop.py, test_backmarket_scraper.py, test_gazelle_scraper.py,
├── test_newegg_scraper.py, test_craigslist_scraper.py,
└── test_price_history.py, test_scooped_deal.py, test_dry_run.py,
    test_listing_age.py, test_condition_bonus.py
docs/
├── marketplace-setup.md       # how to configure login-gated marketplaces
└── marketplace-catalog.md     # researched reference of 34 candidate marketplaces
migrations/
├── env.py                     # Alembic environment (points at src/database.py's models)
└── versions/
    └── 0001_baseline_schema.py  # baseline revision — see "Database Migrations" above
alembic.ini                    # Alembic config (script_location, default/CLI database URL)
Dockerfile                     # container image (alternative runtime, see "Running with Docker")
docker-compose.yml             # local-dev container run, mounts data/ + config.yaml
.dockerignore
```

## Running Tests

```bash
pytest tests/ -v
ruff check .
mypy src/
```

### Persisted test report

`scripts/run_tests_with_report.sh` runs all three of the commands
above and writes a regenerated, human-readable summary to
`test-results/latest.md` — a timestamp, a one-line pass/fail status
for each tool, pytest's pass/fail/error/skip counts, and the full
list of any failing tests (plus the ruff/mypy output when they fail).
`test-results/latest.md` is gitignored (see `test-results/.gitignore`)
since it's fully regenerated every run; only the directory itself is
tracked.

```bash
./scripts/run_tests_with_report.sh
```

This same script runs as an additive step in both CI workflows
(`.github/workflows/scrape-staging.yml` and `.github/workflows/scrape.yml`)
on every run, and the resulting report is uploaded as a downloadable
build artifact (`test-results-staging` / `test-results-production`)
via `actions/upload-artifact` — so you can check the last N runs'
pass/fail history from the Actions tab without digging through raw
logs. It runs with `continue-on-error: true`, so a test/lint failure
is visible in the report and artifact but never blocks the scheduled
scraper run itself.
