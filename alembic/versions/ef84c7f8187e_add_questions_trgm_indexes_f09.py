"""add_questions_trgm_indexes_f09

Revision ID: ef84c7f8187e
Revises: 6360fb6b24dd
Create Date: 2026-11-17 20:45:37.015319

"""

from __future__ import annotations

from alembic import op

revision: str = "ef84c7f8187e"
down_revision: str | None = "6360fb6b24dd"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # pg_trgm 提供 gin_trgm_ops；F02 的 ILIKE '%q%' 标题/正文模糊搜索依赖该扩展。
    # 扩展保留在库级，downgrade 只回收索引（D2：不强制 DROP EXTENSION）。
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_index(
        "ix_questions_body_trgm",
        "questions",
        ["body"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"body": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_questions_title_trgm",
        "questions",
        ["title"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"title": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_questions_title_trgm", table_name="questions")
    op.drop_index("ix_questions_body_trgm", table_name="questions")
