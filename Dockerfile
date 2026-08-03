# ───────────────────────────────────────────────────────────────────
# Dockerfile — containerized runtime for landonkea-apple-products-scraper
# ───────────────────────────────────────────────────────────────────
# WHAT THIS IS: an ADDITIVE alternative way to run the scraper (local
# dev, or self-hosting somewhere that isn't GitHub Actions). The
# primary production runtime is still the GitHub Actions cron
# workflow (.github/workflows/scrape.yml) — this image is not a
# replacement for it and doesn't touch it.
#
# WHY NOT MULTI-STAGE: the obvious win of a multi-stage build (strip
# build tools out of the final image) doesn't apply cleanly here,
# because `playwright install --with-deps chromium` installs system
# libraries (libnss3, libatk, etc.) that Chromium needs at RUNTIME,
# not just at build time — copying only Python site-packages into a
# slimmer final stage would leave Chromium unable to launch. A single
# stage keeps the apt-installed runtime libs and the Python
# dependencies in the same layer where they're actually needed, and
# nothing here requires a C compiler (all deps ship manylinux
# wheels), so there's no build-only bloat to shed anyway.
# ───────────────────────────────────────────────────────────────────

FROM python:3.12-slim

# ── Environment ─────────────────────────────────────────────────────
# PYTHONPATH=/app/src mirrors local dev's `PYTHONPATH=src python3 -m
# main` (see README Quick Start) -- this repo uses a src-layout where
# setuptools maps package-dir {"": "src"}, so top-level modules like
# `main`, `config`, `scrapers` live directly under src/, not
# src.main.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# ── Install Python dependencies ─────────────────────────────────────
# Copy only what's needed to resolve + install dependencies first, so
# Docker's layer cache is reused on rebuilds that only touch scraper
# logic (config.yaml, src/*.py churn far more often than the
# dependency list does).
COPY pyproject.toml README.md ./
COPY src/ ./src/

RUN pip install --upgrade pip && \
    pip install -e .

# ── Install Playwright's browser binary ─────────────────────────────
# Only some scrapers (bestbuy, ebay, offerup, facebook, mercari,
# backmarket -- see src/scrapers/*.py) render pages with Playwright;
# the rest use plain `requests`. All of them share one process
# though, so the image needs Chromium regardless of which scrapers
# are enabled in config.yaml. --with-deps installs the apt packages
# Chromium needs to actually launch headless in a container (this is
# the same flag scrape.yml's GitHub Actions runner uses).
RUN playwright install --with-deps chromium

# ── Application config ──────────────────────────────────────────────
# config.yaml is baked into the image so `docker run` works out of
# the box; docker-compose.yml mounts a local copy over it for anyone
# customizing searches without rebuilding the image.
COPY config.yaml ./

# data/ and docs/data/ are created at runtime (data/listings*.db,
# data/watchlist*.json, docs/data/daily_stats.json) -- pre-create them
# so a bind-mounted empty host directory doesn't cause permission
# surprises, and so a no-mount `docker run` still works standalone.
RUN mkdir -p data docs/data

# ── Entry point ──────────────────────────────────────────────────────
# Matches the real invocation used everywhere else in this project
# (see scrape.yml step 5 and README Quick Start): `python -m main`.
# Flags like --dry-run / --config / --once (see src/main.py's
# docstring) can be appended, e.g.:
#   docker run --rm -v $(pwd)/data:/app/data apple-product-scraper --dry-run
ENTRYPOINT ["python", "-m", "main"]
