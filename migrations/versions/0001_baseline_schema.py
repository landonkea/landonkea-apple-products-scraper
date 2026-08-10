"""baseline schema

Revision ID: 0001
Revises:
Create Date: 2026-08-04

WHAT THIS IS: the starting point for Alembic-managed migrations in
this project. It represents the CURRENT schema exactly as it existed
right before this migration -- i.e. exactly what `create_tables()`
(Base.metadata.create_all) plus the old `_ensure_columns()` ALTER-
TABLE stopgap in src/database.py already produced together. This is
a baseline, not a behavior change: every table/column here already
existed (or was added by _ensure_columns) for anyone running this
project before Alembic was introduced.

WHY THIS MIGRATION IS GUARDED (checks existing tables/columns via
`inspect()` instead of unconditionally calling `op.create_table` /
`op.add_column`): this project has three kinds of database this
migration needs to run cleanly against, all at once, on the very
first `alembic upgrade head`:

  1. A brand new, empty database (nothing exists yet) -- e.g. a
     fresh contributor checkout, or a fresh CI run. Here every
     `create_table`/`add_column` below actually needs to run.

  2. An existing database that already has all three tables AND
     every column (i.e. `_ensure_columns()` already ran against it
     on some previous startup, before this migration existed) -- the
     real dev/staging databases fall in this bucket. Here NOTHING
     below should execute; the schema is already at the target
     state.

  3. An existing database that has the tables but is missing some of
     the columns `_ensure_columns()` used to backfill (e.g.
     `size`/`brand`/`color`, added for the apparel product type,
     which a given committed data/listings.db may predate) -- the
     real production database is currently in this bucket. Here only
     the missing columns should be added; the tables themselves
     already exist and must not be touched.

Without these guards, this migration would raise
"table already exists" / "duplicate column" the moment it ran against
any of the real pre-existing databases in this project (dev, staging,
production all have data already) -- exactly the case this whole
migration exists to handle safely. Later migrations (once every real
database has been stamped/upgraded past this one) don't need this
guard pattern -- it's specific to bridging the pre-Alembic state.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    # ── listings ────────────────────────────────────────────────
    if "listings" not in existing_tables:
        op.create_table(
            "listings",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("source", sa.String(length=50), nullable=False),
            sa.Column("listing_id", sa.String(length=200), nullable=False),
            sa.Column("title", sa.String(length=500), nullable=False),
            sa.Column("price_usd", sa.Float(), nullable=False),
            sa.Column("currency", sa.String(length=3), nullable=True),
            sa.Column("url", sa.Text(), nullable=False),
            sa.Column("condition", sa.String(length=50), nullable=True),
            sa.Column("ram_gb", sa.Integer(), nullable=True),
            sa.Column("storage_gb", sa.Integer(), nullable=True),
            sa.Column("screen_size", sa.Float(), nullable=True),
            sa.Column("chip", sa.String(length=50), nullable=True),
            sa.Column("cpu_cores", sa.Integer(), nullable=True),
            sa.Column("gpu_cores", sa.Integer(), nullable=True),
            sa.Column("size", sa.Float(), nullable=True),
            sa.Column("brand", sa.String(length=100), nullable=True),
            sa.Column("color", sa.String(length=50), nullable=True),
            sa.Column("deal_score", sa.Float(), nullable=True),
            sa.Column("is_great_deal", sa.Boolean(), nullable=True),
            sa.Column("first_seen_at", sa.DateTime(), nullable=True),
            sa.Column("last_seen_at", sa.DateTime(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=True),
            sa.UniqueConstraint("source", "listing_id", name="uq_source_listing"),
        )
        op.create_index(op.f("ix_listings_source"), "listings", ["source"])
        op.create_index(op.f("ix_listings_price_usd"), "listings", ["price_usd"])
    else:
        # Table already exists (every real dev/staging/production
        # database) -- only backfill columns _ensure_columns() used
        # to add, if this particular database predates them.
        existing_columns = {c["name"] for c in inspector.get_columns("listings")}
        optional_columns = [
            sa.Column("cpu_cores", sa.Integer(), nullable=True),
            sa.Column("gpu_cores", sa.Integer(), nullable=True),
            sa.Column("size", sa.Float(), nullable=True),
            sa.Column("brand", sa.String(length=100), nullable=True),
            sa.Column("color", sa.String(length=50), nullable=True),
        ]
        with op.batch_alter_table("listings") as batch_op:
            for column in optional_columns:
                if column.name not in existing_columns:
                    batch_op.add_column(column)

    # ── daily_price_stats ──────────────────────────────────────────
    if "daily_price_stats" not in existing_tables:
        op.create_table(
            "daily_price_stats",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("date", sa.String(length=10), nullable=False),
            sa.Column("product_name", sa.String(length=100), nullable=False),
            sa.Column("group_key", sa.String(length=50), nullable=False),
            sa.Column("min_price", sa.Float(), nullable=False),
            sa.Column("avg_price", sa.Float(), nullable=False),
            sa.Column("max_price", sa.Float(), nullable=False),
            sa.Column("listing_count", sa.Integer(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("date", "group_key", name="uq_date_group_key"),
        )
        op.create_index(op.f("ix_daily_price_stats_date"), "daily_price_stats", ["date"])
        op.create_index(op.f("ix_daily_price_stats_group_key"), "daily_price_stats", ["group_key"])

    # ── price_history ───────────────────────────────────────────────
    if "price_history" not in existing_tables:
        op.create_table(
            "price_history",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("listing_id", sa.Integer(), sa.ForeignKey("listings.id"), nullable=False),
            sa.Column("price_usd", sa.Float(), nullable=False),
            sa.Column("recorded_at", sa.DateTime(), nullable=True),
        )
        op.create_index(op.f("ix_price_history_listing_id"), "price_history", ["listing_id"])
        op.create_index(op.f("ix_price_history_recorded_at"), "price_history", ["recorded_at"])


def downgrade() -> None:
    """Downgrade schema.

    Drops everything this baseline could have created. Since upgrade()
    is guarded (it may have created nothing, some tables, or just
    added a couple of columns depending on what the database already
    had), this simply drops all three tables outright -- reversing a
    baseline migration on a real database with data is not a
    supported operation anyway (there's no way to "un-baseline" columns
    that predate Alembic without data loss), so this is provided only
    for symmetry / fresh-database use (e.g. tests that migrate up and
    back down against a throwaway sqlite file).
    """
    op.drop_table("price_history")
    op.drop_table("daily_price_stats")
    op.drop_table("listings")
