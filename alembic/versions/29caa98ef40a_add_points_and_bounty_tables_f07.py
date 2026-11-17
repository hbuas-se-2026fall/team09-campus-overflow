"""add points and bounty tables (F07)

Revision ID: 29caa98ef40a
Revises: 82908edc9ebf
Create Date: 2026-11-13 11:17:07.132318

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "29caa98ef40a"
down_revision: str | None = "82908edc9ebf"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "point_ledgers",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=50), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_point_ledgers_user_id"),
        "point_ledgers",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "uq_point_ledgers_source_event",
        "point_ledgers",
        ["source", "event_id"],
        unique=True,
    )
    op.create_table(
        "points_accounts",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("balance", sa.Integer(), server_default="0", nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id"),
        sa.CheckConstraint(
            "balance >= 0", name="ck_points_accounts_balance_non_negative"
        ),
    )
    op.create_table(
        "question_bounties",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("question_id", sa.UUID(), nullable=False),
        sa.Column("teacher_id", sa.UUID(), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(length=10), server_default="open", nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["question_id"], ["questions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["teacher_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_question_bounties_question_id"),
        "question_bounties",
        ["question_id"],
        unique=False,
    )
    op.create_index(
        "uq_question_bounties_open",
        "question_bounties",
        ["question_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_question_bounties_open",
        table_name="question_bounties",
        postgresql_where=sa.text("status = 'open'"),
    )
    op.drop_index(
        op.f("ix_question_bounties_question_id"), table_name="question_bounties"
    )
    op.drop_table("question_bounties")
    op.drop_table("points_accounts")
    op.drop_index("uq_point_ledgers_source_event", table_name="point_ledgers")
    op.drop_index(op.f("ix_point_ledgers_user_id"), table_name="point_ledgers")
    op.drop_table("point_ledgers")
