# ───────────────────────────────────────────────────────────────────
# Tests for notifier.format_listing_age()
# ───────────────────────────────────────────────────────────────────
# Surfaces "Listed 4h ago" style age in Discord alerts. Covers:
#   1. Minutes/hours/days formatting boundaries.
#   2. Naive datetimes (as returned by SQLite round-trips) are
#      treated as UTC, not local time.
#   3. None -> empty string (listing with unknown first_seen_at).
# ───────────────────────────────────────────────────────────────────

import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from notifier import format_listing_age


def test_none_returns_empty_string():
    assert format_listing_age(None) == ""


def test_minutes_ago():
    seen = datetime.now(timezone.utc) - timedelta(minutes=15)
    assert format_listing_age(seen) == "Listed 15m ago"


def test_hours_ago():
    seen = datetime.now(timezone.utc) - timedelta(hours=4)
    assert format_listing_age(seen) == "Listed 4h ago"


def test_days_ago():
    seen = datetime.now(timezone.utc) - timedelta(days=3)
    assert format_listing_age(seen) == "Listed 3d ago"


def test_naive_datetime_treated_as_utc():
    """SQLite round-trips DateTime columns back as naive datetimes
    (tzinfo stripped) even though they were stored as UTC -- this
    must not be misread as local time."""
    seen_aware = datetime.now(timezone.utc) - timedelta(hours=5)
    seen_naive = seen_aware.replace(tzinfo=None)
    assert format_listing_age(seen_naive) == "Listed 5h ago"


def test_just_now_rounds_to_one_minute_minimum():
    seen = datetime.now(timezone.utc)
    assert format_listing_age(seen) == "Listed 1m ago"
