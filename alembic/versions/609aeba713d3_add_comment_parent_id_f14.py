"""add_comment_parent_id_f14

Revision ID: 609aeba713d3
Revises: c90363e3c1fb
Create Date: 2026-11-21 20:16:15.794966

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "609aeba713d3"
down_revision: str | None = "c90363e3c1fb"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("comments", sa.Column("parent_id", sa.UUID(), nullable=True))
    op.create_index("ix_comments_parent_id", "comments", ["parent_id"], unique=False)
    op.create_foreign_key(
        "fk_comments_parent_id",
        "comments",
        "comments",
        ["parent_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_comments_no_self_parent",
        "comments",
        "parent_id IS NULL OR parent_id <> id",
    )


def downgrade() -> None:
    op.drop_constraint("ck_comments_no_self_parent", "comments", type_="check")
    op.drop_constraint("fk_comments_parent_id", "comments", type_="foreignkey")
    op.drop_index("ix_comments_parent_id", table_name="comments")
    op.drop_column("comments", "parent_id")
