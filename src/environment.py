# ───────────────────────────────────────────────────────────────────
# Environment awareness — dev / staging / production
# ───────────────────────────────────────────────────────────────────
# WHY THIS FILE EXISTS:
#   This scraper runs in two very different contexts:
#     1. On a developer's laptop, while writing/testing code.
#     2. On GitHub Actions' cron schedule, where it posts real alerts
#        to a live Discord channel and commits to the real production
#        SQLite database file (data/listings.db).
#
#   Without an explicit signal distinguishing those two contexts, a
#   local test run looks *identical* to a real production run: same
#   code, same config.yaml, same database URL, same webhook. That's
#   dangerous — a local test run could spam the real Discord channel
#   with fake "deal" alerts, or worse, write to / lock the same
#   database file that GitHub Actions relies on. (This exact failure
#   happened in practice: a stray local process left the production
#   DB file locked, and the next GitHub Actions run failed with a
#   "readonly database" error.)
#
#   This module gives the rest of the codebase a single, explicit,
#   well-tested source of truth for "which environment am I running
#   in right now?" so other modules (config.py, notifier.py, main.py)
#   can make safe decisions instead of assuming they're always in
#   production.
#
# HOW IT WORKS:
#   We read a single environment variable, ENVIRONMENT, which the
#   operator (a human, or the GitHub Actions workflow file) sets
#   explicitly before running the scraper. It must be one of:
#     - "dev"          → a developer's local machine, iterating on code
#     - "staging"       → a pre-production dry run (e.g. testing a new
#                          scraper against real sites without alerting)
#     - "production"    → the real, live run that posts to the real
#                          Discord channel and touches the real DB
#
# WHY DEFAULT TO "production" WHEN ENVIRONMENT IS UNSET:
#   This looks backwards at first — shouldn't the *safe* default be
#   dev, so unset-by-accident never triggers a live post? In this
#   codebase's case, no: the .github/workflows/scrape.yml file (the
#   ONLY place production alerts have ever been sent from) does not
#   currently set ENVIRONMENT at all, and it must keep working
#   exactly as it always has, with zero behavior change, the moment
#   this file is introduced. So "unset" has to mean "production" to
#   preserve today's real behavior.
#
#   The safety net instead lives on the *local* side: anyone running
#   the scraper locally is expected to explicitly export
#   ENVIRONMENT=dev (documented in README/.env.example) before
#   testing. Forgetting to do that is a real risk, which is exactly
#   why step 5 of this task also adds an explicit
#   `ENVIRONMENT: production` line to the GitHub Actions workflow —
#   making production an intentional, visible declaration there too,
#   rather than a silent fallback nobody can see.
# ───────────────────────────────────────────────────────────────────

import os

# The only valid values for ENVIRONMENT. Kept as a module-level
# constant so it's easy to find/extend, and so both get_environment()
# and any future callers can reference the same canonical list.
VALID_ENVIRONMENTS = ("dev", "staging", "production")


def get_environment() -> str:
    """
    Return the current environment: "dev", "staging", or "production".

    WHAT:
        Reads the ENVIRONMENT environment variable, normalizes it to
        lowercase, and validates it against VALID_ENVIRONMENTS.

    HOW:
        - Missing/unset ENVIRONMENT → defaults to "production" (see
          the module docstring above for why this default is safe
          here: GitHub Actions, the only real production runner,
          historically ran with no ENVIRONMENT var set at all, and
          this function must not change that behavior).
        - Present but with different casing (e.g. "Dev", "PRODUCTION")
          is normalized to lowercase, so operators don't need to
          remember exact casing.
        - Anything outside VALID_ENVIRONMENTS raises ValueError with
          a message naming the bad value and the allowed set, so a
          typo (e.g. ENVIRONMENT=prod) fails loudly at startup rather
          than silently behaving like an unrecognized 4th environment.

    Returns:
        One of "dev", "staging", "production".

    Raises:
        ValueError: if ENVIRONMENT is set to something not in
            VALID_ENVIRONMENTS.
    """
    raw_value = os.environ.get("ENVIRONMENT", "production")
    normalized = raw_value.strip().lower()

    if normalized not in VALID_ENVIRONMENTS:
        raise ValueError(
            f"Invalid ENVIRONMENT={raw_value!r}. Must be one of "
            f"{VALID_ENVIRONMENTS} (case-insensitive)."
        )

    return normalized


def is_production() -> bool:
    """
    Return True if the current environment is "production".

    WHAT:
        A small convenience wrapper around get_environment() for the
        common case of "should this code do the real, live thing?"

    WHY:
        Call sites (notifier.py gating real Discord sends, etc.)
        read more clearly as `if is_production():` than
        `if get_environment() == "production":`, and centralizing the
        comparison here means the "what counts as production" logic
        only has to live in one place.

    Returns:
        True when get_environment() == "production", False for "dev"
        or "staging".
    """
    return get_environment() == "production"
