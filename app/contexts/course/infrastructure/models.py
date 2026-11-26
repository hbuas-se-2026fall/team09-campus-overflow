"""course 上下文 ORM 模型（courses / enrollments），严格遵守零跨上下文外键原则。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.shared.db import Base


class CourseModel(Base):
    """courses 表：存储课程聚合元数据（teacher_id 仅存 UUID，不建跨上下文 FK）。"""

    __tablename__ = "courses"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    code: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    semester: Mapped[str] = mapped_column(String(32), nullable=False)
    teacher_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("code", name="uq_courses_code"),
        Index("ix_courses_semester", "semester"),
        Index("ix_courses_teacher_id", "teacher_id"),
    )


class EnrollmentModel(Base):
    """enrollments 表：存储学生选课记录（student_id 仅存 UUID，不建跨上下文 FK）。"""

    __tablename__ = "enrollments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    course_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("courses.id", ondelete="CASCADE", name="fk_enrollments_course_id"),
        nullable=False,
    )
    student_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    enrolled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("course_id", "student_id", name="uq_enrollments_course_student"),
        Index("ix_enrollments_course_id", "course_id"),
        Index("ix_enrollments_student_id", "student_id"),
    )
