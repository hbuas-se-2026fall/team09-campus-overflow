"""add_reputation_leaderboard_index_f08

Revision ID: 6360fb6b24dd
Revises: 29caa98ef40a
Create Date: 2026-11-17 20:06:00.010728

"""

from __future__ import annotations

from alembic import op

revision: str = "6360fb6b24dd"
down_revision: str | None = "29caa98ef40a"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_index(
        "ix_reputation_occurred_user_inc_delta",
        "reputation_ledgers",
        ["occurred_at", "user_id"],
        unique=False,
        postgresql_include=["delta"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_reputation_occurred_user_inc_delta",
        table_name="reputation_ledgers",
    )
