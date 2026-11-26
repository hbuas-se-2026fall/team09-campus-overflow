"""course 仓储的 SQLAlchemy 异步实现。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.course.domain.course import Course
from app.contexts.course.domain.errors import CourseCodeAlreadyExistsError
from app.contexts.course.domain.value_objects import CourseCode, CourseName, Semester
from app.contexts.course.infrastructure.models import CourseModel


def _to_domain(model: CourseModel) -> Course:
    return Course(
        id=model.id,
        code=CourseCode(model.code),
        name=CourseName(model.name),
        semester=Semester(model.semester),
        teacher_id=model.teacher_id,
        created_at=model.created_at,
    )


def _apply_filters(stmt: Select[Any], semester: Semester | None) -> Select[Any]:
    if semester is not None:
        stmt = stmt.where(CourseModel.semester == semester.value)
    return stmt


def _extract_pg_error_info(exc: IntegrityError) -> tuple[str | None, str | None]:
    orig = exc.orig
    cause = getattr(orig, "__cause__", None)
    pgcode = (
        getattr(orig, "pgcode", None)
        or getattr(orig, "sqlstate", None)
        or (getattr(cause, "sqlstate", None) if cause is not None else None)
        or (getattr(cause, "pgcode", None) if cause is not None else None)
    )
    constraint = (
        getattr(cause, "constraint_name", None) if cause is not None else None
    ) or getattr(orig, "constraint_name", None)
    return (
        pgcode if isinstance(pgcode, str) else None,
        constraint if isinstance(constraint, str) else None,
    )


class SqlAlchemyCourseRepository:
    """CourseRepository 端口的 SQLAlchemy 实现。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, course: Course) -> None:
        self._session.add(
            CourseModel(
                id=course.id,
                code=course.code.value,
                name=course.name.value,
                semester=course.semester.value,
                teacher_id=course.teacher_id,
                created_at=course.created_at,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as exc:
            pgcode, constraint = _extract_pg_error_info(exc)
            if constraint == "uq_courses_code" or (
                pgcode == "23505" and constraint is None
            ):
                raise CourseCodeAlreadyExistsError("课程编号已存在") from exc
            raise

    async def get_by_id(self, course_id: UUID) -> Course | None:
        model = (
            await self._session.execute(
                select(CourseModel).where(CourseModel.id == course_id)
            )
        ).scalar_one_or_none()
        return None if model is None else _to_domain(model)

    async def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        semester: Semester | None = None,
    ) -> tuple[list[Course], int]:
        total = int(
            (
                await self._session.execute(
                    _apply_filters(
                        select(func.count()).select_from(CourseModel), semester
                    )
                )
            ).scalar_one()
        )
        offset = (page - 1) * page_size
        if total == 0 or offset >= total:
            return [], total
        stmt = (
            _apply_filters(select(CourseModel), semester)
            .order_by(CourseModel.created_at.desc(), CourseModel.id.desc())
            .offset(offset)
            .limit(page_size)
        )
        models = (await self._session.execute(stmt)).scalars().all()
        return [_to_domain(model) for model in models], total
