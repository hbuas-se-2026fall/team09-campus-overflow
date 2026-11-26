"""add courses and enrollments tables

Revision ID: 965519fef7b7
Revises: 0c58c26e2c45
Create Date: 2026-11-25 14:56:40.282536

"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "965519fef7b7"
down_revision: str | None = "0c58c26e2c45"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "courses",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("semester", sa.String(length=32), nullable=False),
        sa.Column("teacher_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_courses_code"),
    )
    op.create_index("ix_courses_semester", "courses", ["semester"], unique=False)
    op.create_index("ix_courses_teacher_id", "courses", ["teacher_id"], unique=False)
    op.create_table(
        "enrollments",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("course_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column(
            "enrolled_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["courses.id"],
            name="fk_enrollments_course_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "course_id",
            "student_id",
            name="uq_enrollments_course_student",
        ),
    )
    op.create_index(
        "ix_enrollments_course_id", "enrollments", ["course_id"], unique=False
    )
    op.create_index(
        "ix_enrollments_student_id", "enrollments", ["student_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_enrollments_student_id", table_name="enrollments")
    op.drop_index("ix_enrollments_course_id", table_name="enrollments")
    op.drop_table("enrollments")
    op.drop_index("ix_courses_teacher_id", table_name="courses")
    op.drop_index("ix_courses_semester", table_name="courses")
    op.drop_table("courses")
