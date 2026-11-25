"""add question course_id column f17

Revision ID: 13a011cb2db6
Revises: 965519fef7b7
Create Date: 2026-11-25 15:39:16.167095

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "13a011cb2db6"
down_revision: str | None = "965519fef7b7"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column("questions", sa.Column("course_id", sa.UUID(), nullable=True))
    op.create_index(
        "ix_questions_course_id", "questions", ["course_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_questions_course_id", table_name="questions")
    op.drop_column("questions", "course_id")
