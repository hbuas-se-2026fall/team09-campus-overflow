"""enrollment 仓储的 SQLAlchemy 异步实现。"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.course.domain.enrollment import Enrollment
from app.contexts.course.domain.errors import (
    AlreadyEnrolledError,
    CourseNotFoundError,
)
from app.contexts.course.infrastructure.course_repository import _extract_pg_error_info
from app.contexts.course.infrastructure.models import EnrollmentModel


def _to_domain(model: EnrollmentModel) -> Enrollment:
    return Enrollment(
        id=model.id,
        course_id=model.course_id,
        student_id=model.student_id,
        enrolled_at=model.enrolled_at,
    )


class SqlAlchemyEnrollmentRepository:
    """EnrollmentRepository 端口的 SQLAlchemy 实现。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, enrollment: Enrollment) -> None:
        self._session.add(
            EnrollmentModel(
                id=enrollment.id,
                course_id=enrollment.course_id,
                student_id=enrollment.student_id,
                enrolled_at=enrollment.enrolled_at,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as exc:
            pgcode, constraint = _extract_pg_error_info(exc)
            if constraint == "uq_enrollments_course_student" or (
                pgcode == "23505" and constraint is None
            ):
                raise AlreadyEnrolledError("已选修该课程，请勿重复选课") from exc
            if constraint == "fk_enrollments_course_id" or (
                pgcode == "23503" and constraint is None
            ):
                raise CourseNotFoundError("课程不存在") from exc
            raise

    async def exists(self, course_id: UUID, student_id: UUID) -> bool:
        hit = (
            await self._session.execute(
                select(EnrollmentModel.id).where(
                    EnrollmentModel.course_id == course_id,
                    EnrollmentModel.student_id == student_id,
                )
            )
        ).scalar_one_or_none()
        return hit is not None

    async def list_by_course_paginated(
        self,
        course_id: UUID,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[Enrollment], int]:
        total = int(
            (
                await self._session.execute(
                    select(func.count())
                    .select_from(EnrollmentModel)
                    .where(EnrollmentModel.course_id == course_id)
                )
            ).scalar_one()
        )
        offset = (page - 1) * page_size
        if total == 0 or offset >= total:
            return [], total
        stmt = (
            select(EnrollmentModel)
            .where(EnrollmentModel.course_id == course_id)
            .order_by(EnrollmentModel.enrolled_at.asc(), EnrollmentModel.id.asc())
            .offset(offset)
            .limit(page_size)
        )
        models = (await self._session.execute(stmt)).scalars().all()
        return [_to_domain(model) for model in models], total
