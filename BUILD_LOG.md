# Build Log

How this repo got from an empty folder to what's here now, and a full
spec for rebuilding it from nothing. Part 1 is history (what actually
happened, pulled from `git log`). Part 2 is a rebuild guide written so
an agent or a developer with zero prior context could reconstruct the
whole project from this file alone.

---

## Part 1: How This Got Built

### The starting point (July 28, 2026)

The first commit (`9fc6553`, "initial release — MacBook Pro M5 Max
deal scraper") landed as one working system, not a scaffold that got
filled in later: `config.yaml`, `pyproject.toml`, a `src/` package,
five scrapers (eBay, Swappa, Apple Refurb, Back Market, Mercari), a
SQLite-backed database module, a price analyzer, an email+Discord
notifier, and a GitHub Actions cron workflow, all in one shot, with
tests for config parsing, database operations, and scraper output. The
goal from day one: watch several resale marketplaces for a 14-inch
MacBook Pro on the top M-series chip, and text/Discord the owner when
one shows up cheap.

### Early iteration: making the scrapers actually work (late July)

The very next commits are almost all scraper reliability fixes, which
tells you the real problem in a project like this isn't writing a
scraper once, it's keeping it working against sites that actively
try to block you. In quick succession:

- Auctions were allowed back into eBay results (not just Buy It Now).
- Best Buy Open Box and OfferUp scrapers were added.
- OfferUp got rewritten to use Playwright + `__NEXT_DATA__` JSON
  extraction because plain HTTP requests couldn't get past its
  JavaScript-rendered results.
- A `ModuleNotFoundError` in the packaging config got fixed
  (`setuptools.packages.find`), then the entry point got changed
  twice more (`src.main` → `main` → `python -m main`) before settling
  on the invocation this repo still uses today.
- eBay moved to Playwright after eBay started returning 403s to plain
  requests.
- OfferUp alone went through about eight fix commits in one day
  (Chromium → Firefox → shared fetch helper → back to the original
  working approach) chasing bot detection that only showed up in
  GitHub Actions, never locally. That back-and-forth is real, not a
  fabricated narrative beat, it's visible in the commit history
  between `1b73ef3` and `4696ce9`.
- Back Market, Mercari, and Best Buy all got Playwright added once it
  became clear plain HTTP wasn't enough for any of them either.

By commit `e74c5ed` ("fix: fix Back Market, Mercari, Best Buy... All
7 scrapers now return listings locally"), the project had a working
baseline across every marketplace it supported at the time.

### Broader coverage (late July into August)

Once the core scrapers were stable, the project widened its net:
iPhone 17 Pro Max support, a minimum-price filter (to catch obvious
mispriced/scam listings), multi-product config, then a Gazelle
scraper (PR #1, merged as `64a6d40`) and a Newegg scraper (PR #2/#3,
`6b1c1e7`/`9931c0e`). A Facebook Marketplace stub went in as PR #4
(`2e5b1e9`), inert until session-cookie secrets exist, rather than
skipped entirely, since the scraper-registration plumbing was already
needed.

### Cleanup and testing discipline (early August)

PR #5 (`71899a1`) refactored the Gazelle and Newegg scrapers from
large functions into small, single-purpose methods and added real
unit tests for both, the first sign the codebase was being treated as
something to maintain, not just something to keep shipping features
into. PR #6 (`8296c7b`) tightened iPhone filtering (rejecting
defective/parts-only listings and adding an implausible-price
safeguard). PR #7/#8 (`4967ed1`, `40f4579`) rebuilt the BackMarket
scraper against a real site redesign and added coverage for it.

### The architecture pivot: pluggable product types (PR #9)

`a9bb357` ("generalize matching/scoring into a pluggable
product_type system") is the biggest structural change in the
project's history. Before this, matching/filtering/scoring logic was
written directly against MacBook Pro and iPhone assumptions. This PR
extracted a `ProductTypeHandler` interface (`src/product_types/
base.py`) so a completely different category (with its own field set)
could plug in later without touching the ten scraper files. Everything
built after this point, Apple Vision Pro and the apparel proof-of-
concept, exists because this refactor happened first.

### Real environments (PR #10)

`370c37e` ("DB retention policy, real staging environment, repo audit
cleanup", PR #10) introduced the dev/staging/production model that's
still in place: `src/environment.py`'s `ENVIRONMENT` variable, a
`staging` branch with its own GitHub Actions workflow and its own
scoped SQLite database, and a retention policy so the production
database doesn't grow forever (72h soft-expiry, 180-day hard delete).
Dependabot was configured for the pip ecosystem around the same time
(`3f301a2`).

### Craigslist, and why it's config-driven (PR #11-#14)

Craigslist got added (PR #11, `7a03694`) and then expanded twice
(PR #13, #14) from a single hardcoded metro to a config-driven list of
regions, because Craigslist is organized by city, not by state, and
the owner wanted to cover several metros in one run. The real region
list was deliberately kept out of the committed `config.yaml` (it
reveals approximate location on a public repo) and pushed into a
gitignored `config.local.yaml` locally and a `CRAIGSLIST_REGIONS_YAML`
GitHub Secret in CI.

### The alert system grows past "found a deal" (PR #15-#20)

Four more alert types got layered on top of the original
first-discovery deal alert, each its own PR:

- **Price-drop alerts** (PR #15/16): alert when a listing already in
  the database shows up cheaper on a later scrape.
- **Quick wins batch** (PR #17/18): per-listing price history (one row
  per price *change*, not per scrape), a `--dry-run` flag, listing-age
  display, "scooped deal" alerts (a great deal that vanishes within
  24h was probably bought by someone else), config-driven suspicious-
  price thresholds, and a condition-grade scoring bonus.
- **Watchlist + score transparency + Apple Refurb baseline**
  (PR #19/20): a human-curated watchlist (track one specific URL
  regardless of scoring), a `deal_score_breakdown` so every alert
  shows *why* it scored what it scored, and a live comparison against
  Apple's own refurb pricing when available.

### Making it trustworthy: tests, Docker, a second product type (PR #21-#26)

- PR #21/22 added a persisted, human-readable test report
  (`scripts/run_tests_with_report.sh` → `test-results/latest.md`),
  uploaded as a CI artifact on every run.
- PR #23/24 added the Dockerfile and docker-compose.yml, an additive
  local/self-hosting runtime, not a replacement for the GitHub
  Actions cron job.
- PR #25/26 added `apparel.py`, a second, structurally different
  `ProductTypeHandler` (boots: size/brand/color, not chip/RAM/storage)
  built specifically to prove the PR #9 abstraction actually
  generalizes. It's registered but never wired into a live
  `config.yaml` search, the owner wanted Apple deal alerts, not boots.

### Migrations, iPad Pro, and going public (PR #27-#29)

`_ensure_columns()`, a hand-rolled ALTER-TABLE stopgap, got replaced
with real Alembic migrations (PR #27, later re-landed alongside other
work at `1e04636`/`2000b01`), so schema changes are now a version-
controlled history instead of runtime guessing. The same window added
iPad Pro support, fixed a filtering regression, added a LICENSE file
(the repo went public around here), and kept the real Craigslist
region list out of the public repo. The dynamic run-schedule idea
(read an hour list from `config.yaml` to decide whether a given cron
firing should scrape) was tried and then deliberately reverted in
favor of a single static daily cron trigger, the indirection wasn't
worth it for a project that only ever wants one run a day. That
reversal is still visible today: `config.yaml`'s `schedule:` block is
explicitly commented as informational-only, and `scrape.yml`'s cron
expression is the real source of truth.

### Recent history: Vision Pro, and repo hygiene

The most recent substantive feature is Apple Vision Pro support
(`b686c69`, promoted to main at `05bf06f`), a third `ProductTypeHandler`
built as its own handler rather than an `electronics.py` search entry,
because Vision Pro has no RAM tier and no "Pro/Max" chip suffix,
`ElectronicsHandler.is_relevant()`'s accessory filtering wouldn't work
for it unmodified. Alongside it: a CI workflow that blocks AI-
attribution trailers in commits (`0b2ef93`, later upgraded at
`e4ccf65`), a README rewrite to match the current architecture
(`5ace820`), design-workflow docs (`4e488f5`), and a pass removing em
dashes and AI-sounding phrasing from the README and other markdown
(`390534f`, `46c7328`).

As of this writing: 137 commits, one `main` branch (production), one
`staging` branch, one `dev` branch, and roughly two dozen now-merged
feature/promote branches left over from the PR workflow described
above.

---

## Part 2: Rebuild From Scratch

Assume every file in this repository is gone except this one. Here is
exactly how to reconstruct it, in dependency order. Each step names
the files it produces and what they need to contain functionally,
enough for an experienced Python developer (or an LLM agent) to
write working code without guessing at the design.

### Step 0: Prerequisites

- Python 3.11+ (the Docker image and CI both use 3.12).
- Git, and a GitHub account/repo to push to.
- A Gmail account with an [app password](https://myaccount.google.com/apppasswords)
  (for email alerts) and a Discord server where you can create a
  webhook (Server Settings → Integrations → Webhooks).
- Docker, optional, only needed if you want the containerized runtime.

### Step 1: Scaffold the package

```bash
mkdir landonkea-apple-products-scraper && cd landonkea-apple-products-scraper
git init
mkdir -p src/scrapers src/product_types tests migrations/versions docs/data scripts data
```

Create `pyproject.toml` with:
- `[build-system]`: `setuptools>=68.0`, `setuptools.build_meta`.
- `[project]`: name `landonkea-apple-products-scraper`, `requires-python = ">=3.11"`.
- Runtime dependencies: `requests>=2.31`, `beautifulsoup4>=4.12`,
  `lxml>=5.0`, `sqlalchemy>=2.0`, `alembic>=1.13`, `pyyaml>=6.0`,
  `playwright>=1.40`, `playwright-stealth>=1.0`.
- Dev dependencies (`[project.optional-dependencies].dev`):
  `pytest>=8.0`, `pytest-cov>=4.0`, `ruff>=0.3`, `mypy>=1.8`.
- `[project.scripts]`: `apple-product-scraper = "main:main"`.
- A `setuptools.packages.find` / `package-dir` config pointing at
  `src/`, this is a src-layout project, so top-level modules
  (`main`, `config`, `database`, etc.) live directly under `src/`,
  not under `src.something`. This tripped up the original build
  (see `df4c32a`/`3fcb173`/`ecdeb37` in Part 1), get it right the
  first time by setting `package-dir = {"" = "src"}` and running
  everything as `PYTHONPATH=src python -m main` or `python -m main`
  after `pip install -e .`.
- `[tool.ruff]`: `line-length = 120`, `[tool.ruff.lint] select = ["E", "F"]`
  only, not ruff's full default rule set.
- `[tool.mypy]`: `mypy_path = "src"`, `explicit_package_bases = true`,
  `ignore_missing_imports = true`.

```bash
pip install -e ".[dev]"
playwright install chromium
```

### Step 2: `src/environment.py`

A single-purpose module: read the `ENVIRONMENT` env var, normalize to
lowercase, validate against `("dev", "staging", "production")`, raise
`ValueError` on anything else. **Default to `"production"` when unset**
(not `"dev"`), because the production GitHub Actions workflow
historically ran with no `ENVIRONMENT` set and must keep working
unchanged. Export `get_environment()` and `is_production()`.

### Step 3: `config.yaml` and `src/config.py`

`config.yaml` is the single file an operator edits to change what's
searched, and it has these top-level sections:

- `generations:` — named chip/model generation windows
  (`mac_chip`, `iphone_pro_max`, `ipad_pro`), each with a `tier`,
  `current_gen`, and `lookback` (how many generations back to also
  search). `mac_chip` additionally carries a `core_counts` map for
  scoring bonuses. This is the one section meant to be edited yearly
  as Apple ships new hardware.
- `searches:` — a list of product searches. Each entry: `product_name`,
  `product_type` (`electronics` default, or `vision_pro`/`apparel`),
  either `generation_family` (reuses a `generations:` window) or an
  explicit `chip`/`chip_fallback`, `screen_sizes`, `ram_gb_primary`/
  `ram_gb_fallback`, `storage_gb_min`/`storage_gb_max`, `location`,
  `results_per_size`. Apparel entries instead carry `sizes`,
  `preferred_brands`, `colors`.
- `price:` — `absolute_max_usd`, `great_deal_usd`/`good_deal_usd` (both
  dicts keyed by `ram_gb`, falling back to `storage_gb` for products
  with no RAM tier, e.g. Vision Pro), `top_deals_count`,
  `suspicious_price_ratio`/`suspicious_min_sample` (flags a listing
  priced under half the batch median while claiming new/sealed
  condition), `source_reliability` (optional per-marketplace trust
  overrides).
- `price_drop:` — `enabled`, `min_drop_percent`, `min_drop_usd`, both
  thresholds must clear before a price-drop alert fires.
- `sites:` — one block per marketplace: `enabled`, `search_url`
  template, optional `applicable_product_types` (Apple-only
  storefronts like Apple Refurb/Best Buy/Newegg/Gazelle should list
  `[electronics]` so they're skipped for other product types).
  Craigslist's block additionally has `regions:` (a list, since
  Craigslist is per-metro, not per-state).
- `alerts:` — `email:` (`enabled`, `smtp_server`, `smtp_port`) and
  `discord:` (`enabled`).
- `schedule:` — informational only, `scrape.yml`'s cron expression is
  the real source of truth (see Part 1's note on why the earlier
  config-driven schedule was reverted).
- `database:` — `url`, defaults to `sqlite:///data/listings.db`.

`config.local.yaml.example` documents a gitignored, non-committed
override file (`config.local.yaml`) that deep-merges on top of
`config.yaml` at load time, for settings that are personally
identifying but not secrets (Craigslist regions). `src/config.py`'s
`load_config()` does that merge and returns a typed `Config`
dataclass tree (`SearchConfig`, `PriceConfig`, `SiteConfig`,
`SitesConfig`, `AlertsConfig`, etc.) so the rest of the codebase never
touches raw YAML dicts.

### Step 4: `src/database.py` + Alembic

Three SQLAlchemy models on a `DeclarativeBase`:

- **`Listing`**: `source`, `listing_id` (unique per source), `title`,
  `price_usd`, `currency`, `url`, `condition`, plus the electronics
  spec columns (`ram_gb`, `storage_gb`, `screen_size`, `chip`,
  `cpu_cores`, `gpu_cores`) and the apparel spec columns (`size`,
  `brand`, `color`, always `NULL` for electronics listings),
  `deal_score`, `is_great_deal`, `first_seen_at`, `last_seen_at`,
  `is_active`. A `UniqueConstraint` on `(source, listing_id)` is what
  makes upsert-based deduplication work.
- **`DailyPriceStat`**: one row per `(date, group_key)`, `min_price`/
  `avg_price`/`max_price`/`listing_count`, feeds the GitHub Pages
  trend chart.
- **`PriceHistory`**: `listing_id` (FK to `Listing.id`), `price_usd`,
  `recorded_at`, one row per price *change*, not per scrape (a
  listing whose price never moves doesn't accumulate near-duplicate
  rows every run).

Set up Alembic (`alembic.ini`, `migrations/env.py` pointed at these
models, `migrations/versions/0001_baseline_schema.py` as a baseline
revision that's safe to run against an empty database, an
already-current one, or an older database only missing some of the
newer optional columns). `get_session()` in `database.py` calls
Alembic's `upgrade head` programmatically on every startup, before any
read/write, so there's nothing to run by hand. Also implement
`prune_old_inactive_listings()` (delete listings, and their price
history, inactive 180+ days) and an `expire_stale_listings()`-style
helper (mark inactive after 72h unseen).

### Step 5: `src/scrapers/base.py`, then each scraper

`base.py` defines a `BaseScraper` ABC and a shared `ScrapedListing`
dataclass, plus shared helpers: `fetch_page()` (plain
`requests`+BeautifulSoup, with retry logic and realistic browser
headers) and `fetch_with_playwright()` (headless Chromium, optionally
with `playwright-stealth`, for sites that render results in
JavaScript or actively block plain HTTP). Rate-limit between requests
politely.

Then one file per marketplace, each choosing the strategy that
actually works against that site (verified empirically, not assumed):

| Scraper | Strategy |
|---|---|
| `ebay.py` | Playwright (moved off plain HTTP after 403 bot detection) |
| `swappa.py` | Product page → variant slugs → listing pages |
| `apple_refurb.py` | Plain HTTP + HTML parsing against Apple's evergreen refurb URLs |
| `backmarket.py` | Discover generation links, then parse embedded Nuxt.js JSON |
| `mercari.py` | Playwright + fallback detail-page scraping |
| `bestbuy.py` | Playwright for JS-rendered search results |
| `gazelle.py` | Plain HTTP against buy.gazelle.com's public Shopify JSON endpoints |
| `newegg.py` | Plain HTTP + HTML parsing, bare product-name query only |
| `craigslist.py` | Plain HTTP, loops over every configured metro region |
| `offerup.py` | Playwright, `__NEXT_DATA__` JSON extraction, login-gated stub until session cookie is set |
| `facebook.py` | Login-gated stub, inert (zero network calls) until `FACEBOOK_SESSION_COOKIE` is set |

### Step 6: `src/product_types/`

Define a `ProductTypeHandler` interface in `base.py`: something every
category implements to own its own relevance filtering, spec parsing,
and scoring bonus logic, so `main.py` and the scrapers never hardcode
category-specific rules. Implement:

- `electronics.py`: MacBook Pro/iPhone/iPad Pro. Parses chip, RAM,
  storage, screen size, core counts from listing titles. Filters out
  accessories and broken/locked listings by keyword.
- `vision_pro.py`: its own handler, not an `electronics.py` search
  entry, because Vision Pro has no RAM tier and no chip-suffix
  concept. Matches by storage tier (256/512GB/1TB) and chip (M2 vs.
  the Oct 2025 M5 refresh), with scoring bonuses favoring the newer
  chip and larger storage.
- `apparel.py`: a structurally different second category (boots:
  size/brand/color, a $50 price floor, different accessory keywords)
  built to prove the interface generalizes. Not wired into any live
  `config.yaml` search entry, working and tested, but off by default.

### Step 7: `src/price_analyzer.py`

Score every listing against `great_deal_usd`/`good_deal_usd`
thresholds (keyed by RAM, falling back to storage for RAM-less
products). Build a `deal_score_breakdown` (named components: `base`,
`price_vs_median`, `condition`, `source_reliability`, `spec_bonus`,
plus adjustment components when the suspicious-price safeguard
clamps a score) and a `format_score_breakdown()` renderer for a
compact one-line summary in alerts. Implement the suspicious-price
safeguard (flag new/sealed listings priced under half the batch
median, only once a batch has enough listings for a meaningful
median), `is_meaningful_price_drop()` for price-drop alerts, and
`_compute_apple_refurb_baselines()` to compare a listing against
Apple's own refurb price for the same configuration when available.

### Step 8: `src/notifier.py`, `src/watchlist.py`, `src/stats_tracker.py`, `src/pages_generator.py`

- `notifier.py`: Gmail SMTP email + Discord webhook, four distinct
  alert types (new deal, price drop, scooped deal, watchlist match),
  gated so non-production runs never post to the real channel
  (`is_production()` from `environment.py`, plus a separate
  `DISCORD_WEBHOOK_URL_DEV` for dev/staging).
- `watchlist.py`: load/save a JSON file of hand-picked URLs to track
  regardless of deal score, cross-reference against each run's fresh
  listings, alert on first sighting or any price change (up or down).
  Path is environment-scoped (`watchlist.json` for production,
  `watchlist.dev.json`/`watchlist.staging.json` for the others).
- `stats_tracker.py`: roll up each run's listings into one
  min/avg/max/count row per product generation per day, for the trend
  chart.
- `pages_generator.py`: write `docs/data/daily_stats.json` for the
  GitHub Pages site (`docs/index.html`) to chart.

### Step 9: `src/main.py`

The orchestrator. In order: load config → build the scraper registry
(a dict of source name → scraper class) → for each enabled search,
run every enabled+applicable scraper → convert results to `Listing`
rows, capturing the prior price before upsert (needed for price-drop
detection) → run the price analyzer → record price history for
new/changed prices → check for scooped deals among listings that just
went inactive → match the watchlist → send whichever alerts qualify →
prune old inactive listings → write stats/pages data → print a run
summary. Support `--dry-run`/`--no-alert` (scrape and save normally,
never actually send) as CLI flags.

### Step 10: Tests

One test file per scraper with nontrivial parsing logic, plus
`test_config.py`, `test_database.py`, `test_price_analyzer.py`,
`test_environment.py`, `test_product_types.py`/
`test_product_types_apparel.py`, and one file per alert type
(`test_price_drop.py`, `test_scooped_deal.py`, `test_watchlist.py`,
`test_price_history.py`, `test_listing_age.py`,
`test_condition_bonus.py`, `test_score_transparency.py`,
`test_dry_run.py`). Add `scripts/run_tests_with_report.sh`: run
`pytest`, `ruff check .`, `mypy src/` in sequence, and
`scripts/_render_test_report.py` to turn their output into
`test-results/latest.md`.

### Step 11: Docker

`Dockerfile`: `python:3.12-slim`, single stage (not multi-stage,
`playwright install --with-deps chromium` installs system libraries
Chromium needs at *runtime*, so there's no clean split between a
build stage and a slim final stage). Copy `pyproject.toml`,
`README.md`, `alembic.ini`, `src/`, `migrations/` first, install, then
install the Chromium browser, then copy `config.yaml`. Entrypoint
`["python", "-m", "main"]`.

`docker-compose.yml`: one `scraper` service, `shm_size: "1gb"` (the
default 64MB `/dev/shm` crashes headless Chromium), `ENVIRONMENT`
defaulting to `dev`, an optional `.env` file, and volume mounts for
`./data` (persist the database across runs) and `./config.yaml`
(read-only, edit searches without rebuilding).

### Step 12: GitHub Actions

Three workflows:

- **`.github/workflows/scrape.yml`** (production): triggers on a
  daily cron (`0 13 * * *`, 13 UTC = 6am America/Phoenix) plus
  `workflow_dispatch`. `concurrency` with `cancel-in-progress: false`
  so overlapping runs queue instead of racing on the final git push.
  Steps: checkout (full history), setup Python 3.12, install deps +
  Playwright, run the test-report script (`continue-on-error: true`,
  visibility only, never gates the scrape), write
  `config.local.yaml` from the `CRAIGSLIST_REGIONS_YAML` secret if
  set, run the scraper with `ENVIRONMENT: production` and the alert
  secrets, commit `data/listings.db` + `docs/data/daily_stats.json` +
  `data/watchlist.json` back to `main` if anything changed
  (`[skip ci]` in the commit message), and post a Discord failure
  notice if the run failed.
- **`.github/workflows/scrape-staging.yml`**: same shape, triggers on
  push to the `staging` branch instead of a schedule, runs with
  `ENVIRONMENT: staging` and `DISCORD_WEBHOOK_URL_DEV` instead of the
  real webhook, only ever commits `data/listings.staging.db` back to
  `staging` (never `docs/data/daily_stats.json`, that would silently
  overwrite the real trend chart if this branch ever merges to main).
- **`.github/workflows/docker-build.yml`**: on push/PR to
  `main`/`staging`, builds the image and runs a real `--dry-run` pass
  inside it (`ENVIRONMENT=dev`) as a smoke test that the Dockerfile
  and containerized Playwright setup still work. Separate from, and
  never gating, the two workflows above.

Repo secrets needed (Settings → Secrets and variables → Actions):
`ALERT_EMAIL_FROM`, `ALERT_EMAIL_TO`, `GMAIL_APP_PASSWORD`,
`DISCORD_WEBHOOK_URL`, `DISCORD_WEBHOOK_URL_DEV`, and optionally
`CRAIGSLIST_REGIONS_YAML` (a YAML fragment matching
`config.local.yaml.example`'s shape).

### Step 13: Push and verify

```bash
gh repo create landonkea-apple-products-scraper --public --source=. --push
```

Create `main`, `staging`, and `dev` branches. Add the secrets above.
Enable GitHub Pages, pointed at `docs/`, for the trend chart site.
Trigger `scrape.yml` manually once (`workflow_dispatch`) to confirm
the whole pipeline, scrape → score → alert → commit, works end to
end before waiting for the next real cron firing.

### Step 14: Local verification

```bash
cp .env.example .env               # fill in real values, or leave blank
ENVIRONMENT=dev PYTHONPATH=src python3 -m main --dry-run
pytest tests/ -v
ruff check .
mypy src/
```

A clean run of all four confirms the rebuild is functionally
equivalent to what's described in Part 1.
