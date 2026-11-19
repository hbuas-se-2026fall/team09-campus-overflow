"""add_soft_delete_columns_f13

Revision ID: c90363e3c1fb
Revises: c451483b0660
Create Date: 2026-11-19 10:11:00.904053

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "c90363e3c1fb"
down_revision: str | None = "c451483b0660"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "answers", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "questions", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("questions", "deleted_at")
    op.drop_column("answers", "deleted_at")
