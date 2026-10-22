"""owners and businesses

Revision ID: 0001
Revises:
Create Date: 2026-10-22
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "owners",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(), nullable=False),
        sa.Column("hashed_password", sa.String(), nullable=False),
        sa.Column("full_name", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_owners_email", "owners", ["email"], unique=True)

    op.create_table(
        "businesses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("owners.id"), nullable=False, unique=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("delivery_enabled", sa.Boolean(), nullable=False),
        sa.Column("delivery_fee", sa.Numeric(10, 2), nullable=False),
        sa.Column("pickup_enabled", sa.Boolean(), nullable=False),
        sa.Column("payment_qr_url", sa.String(), nullable=False),
        sa.Column("payment_instructions", sa.String(), nullable=False),
        sa.Column("unique_amount_cents", sa.Boolean(), nullable=False),
        sa.Column("payment_timeout_minutes", sa.Integer(), nullable=False),
        sa.Column("greeting", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("businesses")
    op.drop_index("ix_owners_email", table_name="owners")
    op.drop_table("owners")
