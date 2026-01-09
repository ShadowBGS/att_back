"""add profile fields to users

Revision ID: 0002_add_profile_fields
Revises: 0001_create_users
Create Date: 2026-01-09
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002_add_profile_fields"
down_revision = "0001_create_users"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("external_id", sa.String(length=100), nullable=True))
    op.add_column("users", sa.Column("department", sa.String(length=120), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "profile_completed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "profile_completed")
    op.drop_column("users", "department")
    op.drop_column("users", "external_id")
