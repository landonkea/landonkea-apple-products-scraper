# ───────────────────────────────────────────────────────────────────
# Database models — SQLAlchemy ORM
# ───────────────────────────────────────────────────────────────────
# This file defines what data we store and how.
# Every listing we find becomes a row in the "listings" table.
# ───────────────────────────────────────────────────────────────────

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    create_engine,
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
    SessionLocal = sessionmaker(bind=engine)
    return SessionLocal()
