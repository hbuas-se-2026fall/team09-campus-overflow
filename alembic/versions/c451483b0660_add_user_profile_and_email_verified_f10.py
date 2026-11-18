"""add_user_profile_and_email_verified_f10

Revision ID: c451483b0660
Revises: ef84c7f8187e
Create Date: 2026-11-18 08:44:57.386917

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "c451483b0660"
down_revision: str | None = "ef84c7f8187e"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # F10：校园资料三列为可空；email_verified 对存量用户回填 false（非空）。
    op.add_column(
        "users", sa.Column("nickname", sa.String(length=30), nullable=True)
    )
    op.add_column(
        "users", sa.Column("college", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "users", sa.Column("class_name", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "users",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "email_verified")
    op.drop_column("users", "class_name")
    op.drop_column("users", "college")
    op.drop_column("users", "nickname")
