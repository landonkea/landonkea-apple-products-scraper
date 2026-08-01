# ───────────────────────────────────────────────────────────────────
# Database models — SQLAlchemy ORM
# ───────────────────────────────────────────────────────────────────
# This file defines what data we store and how.
# Every listing we find becomes a row in the "listings" table.
# ───────────────────────────────────────────────────────────────────

from datetime import datetime, timedelta, timezone

from sqlalchemy import (
    create_engine,
    inspect,
    text,
    Column,
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

    # ── Deal scoring (computed) ───────────────────────────────
    deal_score = Column(Float, nullable=True)
    # A score from 0-100 where higher = better deal.
    # The price_analyzer module computes this.

    is_great_deal = Column(Boolean, default=False)
    # True if this listing is below the "great deal" threshold.

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

    This is idempotent — running it multiple times is safe.
    Call this once at startup.
    """
    Base.metadata.create_all(engine)


def _ensure_columns(engine):
    """
    Add any ORM columns missing from an already-existing "listings"
    table.

    `create_tables()` only creates tables that don't exist yet — it
    won't alter a table that's already there, and the committed
    data/listings.db predates cpu_cores/gpu_cores.  This is a
    lightweight stand-in for a real migration tool (no Alembic setup
    exists in this project), safe to call on every startup.
    """
    inspector = inspect(engine)
    if "listings" not in inspector.get_table_names():
        return

    existing_columns = {col["name"] for col in inspector.get_columns("listings")}
    new_columns = {
        "cpu_cores": "INTEGER",
        "gpu_cores": "INTEGER",
    }

    with engine.begin() as conn:
        for name, sql_type in new_columns.items():
            if name not in existing_columns:
                conn.execute(text(f"ALTER TABLE listings ADD COLUMN {name} {sql_type}"))


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
    deleted = (
        db.query(Listing)
        .filter(Listing.is_active == False, Listing.last_seen_at < cutoff)
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
    create_tables(engine)
    _ensure_columns(engine)
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()
