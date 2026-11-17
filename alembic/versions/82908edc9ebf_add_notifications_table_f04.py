"""add notifications table (F04)

Revision ID: 82908edc9ebf
Revises: 46411f564ffa
Create Date: 2026-11-13 11:11:27.382614

"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "82908edc9ebf"
down_revision: str | None = "46411f564ffa"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("recipient_id", sa.UUID(), nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("actor_id", sa.UUID(), nullable=False),
        sa.Column("target_type", sa.String(length=10), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("source_event_id", sa.UUID(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "is_read", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipient_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_notifications_recipient_created",
        "notifications",
        ["recipient_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_notifications_type_source_recipient",
        "notifications",
        ["type", "source_event_id", "recipient_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_notifications_type_source_recipient", table_name="notifications"
    )
    op.drop_index("ix_notifications_recipient_created", table_name="notifications")
    op.drop_table("notifications")
