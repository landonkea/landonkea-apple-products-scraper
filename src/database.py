# ───────────────────────────────────────────────────────────────────
# Database models — SQLAlchemy ORM
# ───────────────────────────────────────────────────────────────────
# This file defines what data we store and how.
# Every listing we find becomes a row in the "listings" table.
# ───────────────────────────────────────────────────────────────────

import os
from datetime import datetime, timedelta, timezone
from typing import Optional  # noqa: F401 -- used only in `# type:` comments below

from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import (
    create_engine,
    Column,
    ForeignKey,
    Integer,
    Float,
    String,
    DateTime,
    Boolean,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Session,
    sessionmaker,
)


# ── Base class for all database models ────────────────────────────
class Base(DeclarativeBase):
    """
    Every database table inherits from this.
    
    SQLAlchemy uses it to know what tables to create.
    """
    pass


# ── The listings table ────────────────────────────────────────────
# Each row = one product listing found on a marketplace.
class Listing(Base):
    """
    A single listing scraped from a marketplace.
    
    We store enough info to:
      1. Deduplicate (don't alert twice for the same item)
      2. Build the alert message (title, price, link)
      3. Track price history over time
    """
    # ── Table name in SQLite ──────────────────────────────────
    __tablename__ = "listings"

    # ── Primary key ───────────────────────────────────────────
    id = Column(Integer, primary_key=True, autoincrement=True)

    # ── What site this came from ──────────────────────────────
    source = Column(String(50), nullable=False, index=True)
    # Examples: "ebay", "swappa", "apple_refurb", "backmarket", "mercari"

    # ── The marketplace's own ID for this listing ─────────────
    # Used for deduplication — if we see the same listing_id
    # from the same source, we update instead of inserting.
    listing_id = Column(String(200), nullable=False)

    # ── Listing details ───────────────────────────────────────
    title = Column(String(500), nullable=False)
    # The full title of the listing, e.g. "MacBook Pro 14\" M5 Max 128GB"

    price_usd = Column(Float, nullable=False, index=True)
    # The listed price in US dollars (as a number, so we can sort).

    currency = Column(String(3), default="USD")
    # Currency code — almost always USD for these sites.

    url = Column(Text, nullable=False)
    # Direct link to the listing page.

    condition = Column(String(50), nullable=True)
    # e.g. "New", "Open Box", "Used", "Certified Refurbished", "Excellent"

    # ── Specs parsed from the listing title ───────────────────
    ram_gb = Column(Integer, nullable=True)
    # How much RAM the listing has, e.g. 128 or 64.

    storage_gb = Column(Integer, nullable=True)
    # Storage in GB (e.g. 2048 for 2TB, 4096 for 4TB).

    screen_size = Column(Float, nullable=True)
    # Screen size in inches (we filter for 14").

    chip = Column(String(50), nullable=True)
    # Chip name parsed from title, e.g. "M5 Max".

    cpu_cores = Column(Integer, nullable=True)
    # CPU core count parsed from title, e.g. 16.

    gpu_cores = Column(Integer, nullable=True)
    # GPU core count parsed from title, e.g. 40.

    # ── Apparel-specific specs (see src/product_types/apparel.py) ──
    # Always NULL for electronics listings -- only populated when the
    # active search's product_type is "apparel". Proves the same
    # "listings" table (not a per-category table) can carry a second,
    # structurally different product type's specs alongside chip/RAM/
    # storage, same idea as cpu_cores/gpu_cores being optional and
    # unused by earlier rows.
    size = Column(Float, nullable=True)
    # US size, e.g. 10.5.

    brand = Column(String(100), nullable=True)
    # e.g. "Red Wing", "Wolverine".

    color = Column(String(50), nullable=True)
    # e.g. "black", "brown".

    # ── Deal scoring (computed) ───────────────────────────────
    deal_score = Column(Float, nullable=True)
    # A score from 0-100 where higher = better deal.
    # The price_analyzer module computes this.

    is_great_deal = Column(Boolean, default=False)
    # True if this listing is below the "great deal" threshold.

    # ── Runtime-only scoring attributes (NOT database columns) ──
    # These are plain Python attributes -- not Column(...) -- set by
    # PriceAnalyzer during analyze() and read by Notifier right after,
    # within the same process/run. They're never written to SQLite and
    # never survive past the run that computed them (a fresh Listing
    # loaded from the database on the next run starts back at the
    # class-level default of None until analyze() runs again). This is
    # deliberate: both are cheap to recompute every run from data
    # that's already fully captured elsewhere (deal_score's inputs,
    # and whatever Apple Refurb listings are in the current batch), so
    # persisting them would just be one more thing that could go stale
    # -- see price_analyzer.py's _score_listing()/analyze() docstrings.
    # NOTE: deliberately NOT type-annotated (`x: Optional[dict] = None`)
    # -- SQLAlchemy 2.0's Annotated Declarative form interprets a bare
    # type-annotated class attribute as an attempt to map a column and
    # raises MappedAnnotationError unless wrapped in Mapped[] (or the
    # class opts out via __allow_unmapped__). Plain, unannotated class
    # attributes are simply ordinary Python class attributes and don't
    # trigger that check -- exactly what's wanted here.
    deal_score_breakdown = None  # type: Optional[dict]
    # Named components that sum to deal_score (base/price/condition/
    # source/spec bonuses, plus any clamp/suspicious-cap adjustment).
    # Powers the "why this scored X" transparency feature -- see
    # price_analyzer.py's format_score_breakdown().

    apple_refurb_price = None  # type: Optional[float]
    # The lowest Apple Refurb price seen this run for this listing's
    # exact (chip, ram_gb, storage_gb) config -- None if Apple Refurb
    # isn't carrying that config in the current batch, or this
    # listing isn't actually cheaper than it (see
    # PriceAnalyzer._compute_apple_refurb_baselines()).

    vs_apple_refurb_pct = None  # type: Optional[float]
    # How far below apple_refurb_price this listing is, as a percent
    # (e.g. 42.0 for "42% below Apple's own price for this config").
    # None whenever apple_refurb_price is None.

    # ── Timestamps ────────────────────────────────────────────
    first_seen_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    # When we first found this listing.

    last_seen_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                          onupdate=lambda: datetime.now(timezone.utc))
    # When we last saw it (updated every scrape in case price changed).

    is_active = Column(Boolean, default=True)
    # False if the listing is no longer available (sold/expired).

    # ── Make sure we don't store duplicates ───────────────────
    __table_args__ = (
        UniqueConstraint("source", "listing_id",
                         name="uq_source_listing"),
    )

    def __repr__(self) -> str:
        """How this row looks when printed (useful for debugging)."""
        return (
            f"<Listing(id={self.id}, source='{self.source}', "
            f"price=${self.price_usd:.0f}, ram={self.ram_gb}GB, "
            f"deal_score={self.deal_score})>"
        )


# ── Daily price-stat table (for trend charts) ─────────────────────
# One row per (date, group_key) — e.g. ("2026-07-31", "M5 Max").
# group_key is the chip generation for MacBook Pro searches, or the
# matched model generation string for iPhone searches. Rows are
# upserted (overwritten) on every run, so the value for "today"
# reflects the latest scrape of the day; once the day rolls over,
# that row is frozen as history for the trend chart.
class DailyPriceStat(Base):
    """Daily min/avg/max price per product generation, for trend charts."""
    __tablename__ = "daily_price_stats"

    id = Column(Integer, primary_key=True, autoincrement=True)

    date = Column(String(10), nullable=False, index=True)
    # UTC date as "YYYY-MM-DD".

    product_name = Column(String(100), nullable=False)
    # e.g. "MacBook Pro" or "iPhone Pro Max" — which search this came from.

    group_key = Column(String(50), nullable=False, index=True)
    # e.g. "M5 Max" or "iPhone 17 Pro Max" — the generation being tracked.

    min_price = Column(Float, nullable=False)
    avg_price = Column(Float, nullable=False)
    max_price = Column(Float, nullable=False)
    listing_count = Column(Integer, nullable=False)

    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))

    __table_args__ = (
        UniqueConstraint("date", "group_key", name="uq_date_group_key"),
    )

    def __repr__(self) -> str:
        return (
            f"<DailyPriceStat(date='{self.date}', group='{self.group_key}', "
            f"min=${self.min_price:.0f}, avg=${self.avg_price:.0f}, "
            f"max=${self.max_price:.0f}, n={self.listing_count})>"
        )


# ── Per-listing price history ──────────────────────────────────────
# DailyPriceStat (above) is a per-generation daily aggregate — great
# for trend charts, but it can't answer "what has THIS listing's
# price actually done over time" (e.g. did this exact eBay listing
# get marked down twice before it sold?). This table is that: one row
# per (listing, price-at-a-point-in-time), written whenever a scrape
# sees a listing for the first time OR sees its price change. Rows
# are never overwritten -- each is a permanent point in that listing's
# price timeline.
#
# WHY NOT WRITE A ROW ON EVERY SCRAPE: the scraper runs every few
# hours; a listing whose price never moves would otherwise accumulate
# a near-duplicate row per run for as long as it stays listed, which
# is pure noise for a "price history" (nothing changed) and would
# make this table grow unboundedly fast. Writing only on
# insert-or-price-change keeps every row meaningful: each one marks
# an actual price point.
class PriceHistory(Base):
    """One price observation for one listing, at a point in time."""
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True, autoincrement=True)

    listing_id = Column(Integer, ForeignKey("listings.id"), nullable=False, index=True)
    # FK to Listing.id (not the marketplace's own listing_id) -- ties
    # this row to a specific row in the listings table.

    price_usd = Column(Float, nullable=False)
    # The price recorded at this point in time.

    recorded_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    # When this price was observed.

    def __repr__(self) -> str:
        return (
            f"<PriceHistory(listing_id={self.listing_id}, "
            f"price=${self.price_usd:.0f}, recorded_at={self.recorded_at})>"
        )


def record_price_history(db, listing: Listing, price_usd: float) -> bool:
    """
    Append a PriceHistory row for `listing` if its price is new or
    has changed since the last recorded point.

    Args:
        db: Database session.
        listing: The Listing ORM object (must already have an id,
            i.e. already inserted/flushed).
        price_usd: The price to record.

    Returns:
        True if a new PriceHistory row was added, False if the last
        recorded price already matches (nothing written).
    """
    last = (
        db.query(PriceHistory)
        .filter(PriceHistory.listing_id == listing.id)
        .order_by(PriceHistory.recorded_at.desc())
        .first()
    )
    if last is not None and last.price_usd == price_usd:
        return False

    db.add(PriceHistory(listing_id=listing.id, price_usd=price_usd))
    return True


# ── Database connection ───────────────────────────────────────────
# This is how the rest of the code talks to SQLite.
# Usage:
#     db = get_session("sqlite:///data/listings.db")
#     db.add(my_listing)
#     db.commit()

def get_engine(database_url: str):
    """
    Create a database engine (the connection to SQLite).
    
    Args:
        database_url: e.g. "sqlite:///data/listings.db"
    
    Returns:
        A SQLAlchemy Engine object.
    """
    # `echo=False` means "don't log every SQL query" (keeps output clean).
    # `connect_args` tells SQLite to allow multiple readers at once.
    engine = create_engine(
        database_url,
        echo=False,
        connect_args={"check_same_thread": False},
    )
    return engine


def create_tables(engine):
    """
    Create all tables that don't exist yet.

    This is idempotent — running it multiple times is safe. Kept
    around for direct ORM-only use (e.g. tests that want a schema
    without going through Alembic) — normal startup uses
    run_migrations() below instead, which is what actually keeps a
    real (possibly pre-existing) database's schema current.
    """
    Base.metadata.create_all(engine)


# ── Project root, for locating alembic.ini/migrations/ regardless of
# the process's current working directory (GitHub Actions, Docker,
# and a developer's shell all differ here). src/database.py -> src/
# -> repo root is two levels up.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_migrations(database_url: str) -> None:
    """
    Bring the database at `database_url` up to the latest Alembic
    migration ("head").

    This replaces the old create_tables() + _ensure_columns() pair as
    the thing that keeps a database's schema current on startup.
    Unlike create_tables() (only creates missing tables) and the old
    _ensure_columns() (a hand-rolled ALTER-TABLE stopgap, only ever
    covered the "listings" table), this is a real, versioned schema
    history — see migrations/versions/0001_baseline_schema.py, which
    reproduces exactly what those two used to produce together as
    Alembic's baseline revision, and every migration since covers the
    rest.

    Safe to call every startup, against any database: a brand new
    empty file, an existing dev/staging database already fully
    migrated (no-op), or a database that's never seen Alembic before
    (e.g. the committed production data/listings.db) — Alembic
    creates its own "alembic_version" bookkeeping table the first
    time it runs against a database and picks up from there on every
    call after.

    Args:
        database_url: e.g. "sqlite:///data/listings.db" — the same,
            already environment-scoped URL passed to get_engine().
    """
    cfg = AlembicConfig(os.path.join(_PROJECT_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(_PROJECT_ROOT, "migrations"))
    # Override the placeholder/default URL in alembic.ini with the
    # real, already environment-scoped URL for this run — see
    # migrations/env.py for how this value gets picked up.
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


# ── Retention policy ────────────────────────────────────────────────
# WHY THIS EXISTS: main.py's expire_stale_listings() marks a listing
# inactive after 72 hours of not being seen again — but it never
# deletes the row, so the "listings" table grows forever (every
# listing any scraper has ever found, active or not, stays in the
# database indefinitely). This function is the other half: it hard-
# deletes listings that have been INACTIVE for a long time, so old,
# long-dead listings eventually actually leave the database instead
# of accumulating for years.
#
# WHY THIS IS SAFE: the price-trend charts (docs/data/daily_stats.json,
# generated by src/pages_generator.py) read from DailyPriceStat, a
# separate table that already stores the aggregated min/avg/max/count
# per day per generation — it has no foreign key or other reference
# to individual Listing rows. Deleting old Listing rows never touches
# that aggregated history, so the trend charts are completely
# unaffected by this pruning.
RETENTION_DAYS = 180  # ~6 months


def prune_old_inactive_listings(db, days: int = RETENTION_DAYS) -> int:
    """
    Permanently delete listings that have been inactive for a long time.

    WHAT: Deletes Listing rows where is_active is False AND
    last_seen_at is older than `days` days ago. Active listings are
    never touched, regardless of age — only long-dead ones.

    HOW: A single bulk DELETE, not a per-row Python loop — this table
    can accumulate thousands of rows over months, so avoiding an
    N-query round trip matters here (unlike expire_stale_listings(),
    which needs to load full ORM objects to flip is_active on each
    one).

    WHY 180 DAYS: 72-hour expiry (see main.py) already means "no
    longer for sale" listings stop appearing in alerts/deals almost
    immediately — this is a much longer, separate window purely about
    not accumulating an ever-growing SQLite file. 180 days keeps
    several months of recently-dead listings around (useful if you
    ever want to look back at "what did I miss"), while still
    eventually letting genuinely old rows go.

    Args:
        db: Database session.
        days: How long a listing must have been inactive before it's
            deleted. Defaults to RETENTION_DAYS (180).

    Returns:
        The number of rows deleted.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    stale_ids = [
        row.id
        for row in db.query(Listing.id)
        .filter(Listing.is_active == False, Listing.last_seen_at < cutoff)
        .all()
    ]

    if not stale_ids:
        return 0

    # Delete PriceHistory rows first -- there's no FK cascade set up
    # on SQLite by default, so orphaned history rows would otherwise
    # accumulate forever once their parent Listing is gone.
    db.query(PriceHistory).filter(PriceHistory.listing_id.in_(stale_ids)).delete(
        synchronize_session=False
    )
    deleted = (
        db.query(Listing)
        .filter(Listing.id.in_(stale_ids))
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted


def get_session(database_url: str) -> Session:
    """
    Get a database session for reading/writing.
    
    Args:
        database_url: e.g. "sqlite:///data/listings.db"
    
    Returns:
        A SQLAlchemy Session object.
    
    Usage:
        db = get_session("sqlite:///data/listings.db")
        listing = db.query(Listing).first()
    """
    engine = get_engine(database_url)
    run_migrations(database_url)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()
