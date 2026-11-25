"""add_rbac_roles_and_answer_verification_f15

Revision ID: 0c58c26e2c45
Revises: 609aeba713d3
Create Date: 2026-11-25 10:30:49.473913

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "0c58c26e2c45"
down_revision: str | None = "609aeba713d3"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.execute(
        "INSERT INTO roles (name) VALUES ('ta'), ('admin') ON CONFLICT (name) DO NOTHING"
    )
    op.add_column(
        "answers",
        sa.Column(
            "is_teacher_verified",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column("answers", sa.Column("verified_by", sa.UUID(), nullable=True))
    op.add_column(
        "answers",
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_answers_verified_by",
        "answers",
        "users",
        ["verified_by"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_answers_verified_by", "answers", type_="foreignkey")
    op.drop_column("answers", "verified_at")
    op.drop_column("answers", "verified_by")
    op.drop_column("answers", "is_teacher_verified")
    op.execute("DELETE FROM roles WHERE name IN ('ta', 'admin')")
