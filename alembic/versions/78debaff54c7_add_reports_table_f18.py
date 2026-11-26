"""add reports table f18

Revision ID: 78debaff54c7
Revises: 13a011cb2db6
Create Date: 2026-11-25 17:17:38.468399

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "78debaff54c7"
down_revision: str | None = "13a011cb2db6"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "reports",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("reporter_id", sa.UUID(), nullable=False),
        sa.Column("target_type", sa.String(length=16), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.String(length=500), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("resolution_action", sa.String(length=32), nullable=True),
        sa.Column("resolution_note", sa.String(length=500), nullable=True),
        sa.Column("resolved_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'resolved', 'dismissed')",
            name="ck_reports_status",
        ),
        sa.CheckConstraint(
            "target_type IN ('question', 'answer')",
            name="ck_reports_target_type",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_reports_reporter_id", "reports", ["reporter_id"], unique=False)
    op.create_index(
        "ix_reports_status_created", "reports", ["status", "created_at"], unique=False
    )
    op.create_index(
        "ix_reports_target", "reports", ["target_type", "target_id"], unique=False
    )
    op.create_index(
        "uq_reports_pending_reporter_target",
        "reports",
        ["reporter_id", "target_type", "target_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_reports_pending_reporter_target",
        table_name="reports",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_index("ix_reports_target", table_name="reports")
    op.drop_index("ix_reports_status_created", table_name="reports")
    op.drop_index("ix_reports_reporter_id", table_name="reports")
    op.drop_table("reports")
