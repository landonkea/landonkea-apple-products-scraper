"""add ebike columns to listings

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-14

WHAT THIS IS: adds the columns src/product_types/ebike.py's
ScrapedListing/Listing fields need (wheel_size_in, fat_tire,
step_through, folding, battery_voltage, battery_ah, battery_wh,
motor_watts_nominal, motor_watts_peak, weight_capacity_lb, brake_type,
suspension, ul_certified), all nullable, always NULL for pre-existing
electronics/apparel rows -- same shape as 0001's size/brand/color
addition for apparel.

WHY GUARDED (checks existing columns via inspect() instead of an
unconditional op.add_column): this repo's `alembic current` shows no
stamped revision against the committed production data/listings.db at
authoring time, meaning its actual migration history is uncertain
(the app's own run_migrations() may or may not have been run against
this exact checkout's copy of that file). Guarding against columns
that might already exist means this migration is safe to run whether
or not some earlier process already added them by another path, same
defensive rationale as 0001's own guard, see that file's docstring.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: Union[str, Sequence[str], None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


NEW_COLUMNS = [
    sa.Column("wheel_size_in", sa.Float(), nullable=True),
    sa.Column("fat_tire", sa.Boolean(), nullable=True),
    sa.Column("step_through", sa.Boolean(), nullable=True),
    sa.Column("folding", sa.Boolean(), nullable=True),
    sa.Column("battery_voltage", sa.Integer(), nullable=True),
    sa.Column("battery_ah", sa.Float(), nullable=True),
    sa.Column("battery_wh", sa.Float(), nullable=True),
    sa.Column("motor_watts_nominal", sa.Integer(), nullable=True),
    sa.Column("motor_watts_peak", sa.Integer(), nullable=True),
    sa.Column("weight_capacity_lb", sa.Integer(), nullable=True),
    sa.Column("brake_type", sa.String(length=20), nullable=True),
    sa.Column("suspension", sa.Boolean(), nullable=True),
    sa.Column("ul_certified", sa.Boolean(), nullable=True),
]


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_columns = {c["name"] for c in inspector.get_columns("listings")}

    with op.batch_alter_table("listings") as batch_op:
        for column in NEW_COLUMNS:
            if column.name not in existing_columns:
                batch_op.add_column(column)


def downgrade() -> None:
    """Downgrade schema: drop every column this migration could have added."""
    with op.batch_alter_table("listings") as batch_op:
        for column in NEW_COLUMNS:
            batch_op.drop_column(column.name)
