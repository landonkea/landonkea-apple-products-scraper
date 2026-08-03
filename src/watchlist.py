# ───────────────────────────────────────────────────────────────────
# Watchlist — track specific listings by URL, get alerted on price
# changes regardless of deal score / great-deal thresholds
# ───────────────────────────────────────────────────────────────────
# WHAT: Every other alert type in this project (great/good deal,
# price drop, scooped deal) is about the MARKET as a whole -- "here's
# what's good right now." A watchlist entry is the opposite: a user
# manually decided ONE specific listing (found by hand, e.g. on eBay)
# is worth following, and wants to hear about it -- new sighting or
# price change -- even if it would never otherwise rank as a top deal
# (maybe the RAM/storage doesn't match the configured search at all).
#
# HOW: Entries live in data/watchlist.json, a plain JSON array a user
# hand-edits to add a "url" (and optional "note"). Every run,
# match_watchlist_entries() cross-references entries against that
# run's freshly scraped listings; find_watchlist_alerts() narrows
# that down to entries whose price actually changed since the last
# alert (or are being seen for the first time); main.py sends a
# dedicated Discord alert for those via Notifier.send_watchlist_alert()
# and record_watchlist_alerts() updates each entry's
# "last_alerted_price" so the same unchanged price doesn't re-alert
# every 6-hour run forever.
#
# WHY A FLAT JSON FILE (not a database table): this only ever needs
# to be hand-edited by a human (paste a URL, save) and read/rewritten
# once per run -- the same "data/*.json as lightweight config/state"
# pattern already used by data/discord_messages.json (see notifier.py's
# _store_message_id/_cleanup_old_messages). A database table would add
# a migration and ORM plumbing for a handful of rows a human maintains
# by hand.
# ───────────────────────────────────────────────────────────────────

import json
import os
from datetime import datetime, timezone

from database import Listing
from notifier import clean_url

DEFAULT_WATCHLIST_PATH = "data/watchlist.json"


def watchlist_path_for_environment(environment: str) -> str:
    """
    Return the watchlist file path scoped to `environment`, mirroring
    config.py's _environment_scoped_db_url for the database file.

    WHY: Same reasoning as the database's per-environment file --  a
    dev/staging test run must never read or silently overwrite the
    real production watchlist (data/watchlist.json), and production
    must never see a stray entry a developer was only using to test
    locally. "production" keeps the plain, unscoped path (so it
    matches what's already committed to the repo today); "dev" and
    "staging" get their own sibling file, e.g.
    "data/watchlist.dev.json".

    Args:
        environment: One of "dev", "staging", "production" -- usually
            Config.environment.

    Returns:
        A file path, always ending in ".json".
    """
    if environment == "production":
        return DEFAULT_WATCHLIST_PATH
    root, ext = os.path.splitext(DEFAULT_WATCHLIST_PATH)
    return f"{root}.{environment}{ext}"


def load_watchlist(path: str = DEFAULT_WATCHLIST_PATH) -> list[dict]:
    """
    Load watchlist entries from `path`.

    Entry shape (only "url" is required on input -- everything else
    is populated/maintained automatically once an entry first matches
    a scraped listing):
        {
          "url": "https://www.ebay.com/itm/123456789",  # required
          "note": "must buy under $3500",                # optional, free text
          "source": "ebay",                # auto-filled on first match
          "listing_id": "123456789",       # auto-filled on first match
          "last_alerted_price": 3800.0,    # set after every alert sent
          "last_alerted_at": "2026-08-03T00:00:00+00:00"
        }

    Returns:
        A list of entry dicts, in file order. Empty list if the file
        doesn't exist (no watchlist configured -- this is the normal,
        default state) or doesn't contain a JSON array.
    """
    if not os.path.exists(path):
        return []
    with open(path) as f:
        data = json.load(f)
    if not isinstance(data, list):
        return []
    return data


def save_watchlist(entries: list[dict], path: str = DEFAULT_WATCHLIST_PATH) -> None:
    """Persist `entries` back to `path` (creating the parent dir if needed)."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w") as f:
        json.dump(entries, f, indent=2)
        f.write("\n")


def _entry_matches(entry: dict, listing: Listing) -> bool:
    """
    True if `entry` identifies the same listing as `listing`.

    Prefers matching by (source, listing_id) -- the database's own
    dedup key (see Listing's uq_source_listing constraint), and the
    more robust match once an entry has been resolved once (see
    match_watchlist_entries()). Falls back to a cleaned-URL comparison
    for an entry that hasn't been resolved yet -- a brand-new,
    hand-added entry only ever has a "url".
    """
    if entry.get("source") and entry.get("listing_id"):
        return (
            entry["source"] == listing.source
            and str(entry["listing_id"]) == str(listing.listing_id)
        )
    entry_url = entry.get("url")
    if not entry_url:
        return False
    return clean_url(entry_url) == clean_url(listing.url)


def match_watchlist_entries(
    entries: list[dict], listings: list[Listing]
) -> list[tuple[dict, Listing]]:
    """
    Cross-reference watchlist entries against this run's listings.

    WHAT: For every watchlist entry, finds the listing (if any) in
    `listings` it refers to.

    HOW: `entries` is mutated IN PLACE -- on a match, an entry's
    "source"/"listing_id" are backfilled if not already set, so future
    runs can match it reliably via the stable (source, listing_id) key
    instead of depending on the scraped URL staying byte-for-byte
    identical to whatever was originally pasted in. The caller is
    responsible for persisting `entries` afterward (see
    save_watchlist()) if this resolution should stick.

    Args:
        entries: Watchlist entries from load_watchlist().
        listings: Listings from the current run to check against --
            typically one search's freshly upserted `db_listings` (see
            main.py's _run_one_search()).

    Returns:
        (entry, listing) pairs for every entry that matched a listing
        in `listings`. An entry with no match is simply omitted --
        most watched listings won't appear in every single run (not
        sold, just not part of this particular product search, or a
        marketplace's scraper hit an error this run), and that's
        expected, not an error.
    """
    matches: list[tuple[dict, Listing]] = []
    for entry in entries:
        for listing in listings:
            if _entry_matches(entry, listing):
                if not entry.get("source"):
                    entry["source"] = listing.source
                if not entry.get("listing_id"):
                    entry["listing_id"] = listing.listing_id
                matches.append((entry, listing))
                break
    return matches


def find_watchlist_alerts(
    matches: list[tuple[dict, Listing]],
) -> list[tuple[dict, Listing]]:
    """
    Narrow matched (entry, listing) pairs down to the ones actually
    worth alerting on THIS run.

    WHAT: A watchlist alert should fire the first time a tracked
    listing is ever matched (no `last_alerted_price` recorded yet) and
    again whenever its price changes -- UP or DOWN. Unlike the
    price-drop alert (which only cares about drops, since it's about
    "is this a good time to buy"), a watched listing's price going up
    is just as relevant to someone deciding whether to act now versus
    later. It should NOT re-fire every run for a price that hasn't
    moved since the last alert -- that would spam the same unchanged
    listing every 6 hours indefinitely.

    Args:
        matches: Output of match_watchlist_entries().

    Returns:
        The subset of `matches` representing a new alert-worthy state
        (first sighting, or a price change since the last alert).
    """
    alerts = []
    for entry, listing in matches:
        last_price = entry.get("last_alerted_price")
        if last_price is None or float(last_price) != float(listing.price_usd):
            alerts.append((entry, listing))
    return alerts


def record_watchlist_alerts(alerts: list[tuple[dict, Listing]]) -> None:
    """
    Update each alerted entry's bookkeeping fields IN PLACE so the
    next run doesn't re-alert on the same, unchanged price.

    Args:
        alerts: (entry, listing) pairs that were just alerted on --
            typically the return value of find_watchlist_alerts().
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    for entry, listing in alerts:
        entry["last_alerted_price"] = listing.price_usd
        entry["last_alerted_at"] = now_iso
