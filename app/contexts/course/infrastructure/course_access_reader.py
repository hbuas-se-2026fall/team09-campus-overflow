"""跨上下文课程只读查询适配器（实现 CourseAccessReader 端口）。"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.course.application.ports import CourseSummary
from app.contexts.course.infrastructure.models import CourseModel, EnrollmentModel


class SqlAlchemyCourseAccessReader:
    """CourseAccessReader 的 SQLAlchemy 只读实现（显式列投影）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_summary(self, course_id: UUID) -> CourseSummary | None:
        row = (
            await self._session.execute(
                select(
                    CourseModel.id,
                    CourseModel.code,
                    CourseModel.name,
                    CourseModel.semester,
                    CourseModel.teacher_id,
                ).where(CourseModel.id == course_id)
            )
        ).one_or_none()
        if row is None:
            return None
        return CourseSummary(
            course_id=row[0],
            code=row[1],
            name=row[2],
            semester=row[3],
            teacher_id=row[4],
        )

    async def get_summaries(
        self, course_ids: Iterable[UUID]
    ) -> dict[UUID, CourseSummary]:
        unique_ids = list(dict.fromkeys(course_ids))
        if not unique_ids:
            return {}
        rows = (
            await self._session.execute(
                select(
                    CourseModel.id,
                    CourseModel.code,
                    CourseModel.name,
                    CourseModel.semester,
                    CourseModel.teacher_id,
                ).where(CourseModel.id.in_(unique_ids))
            )
        ).all()
        return {
            row[0]: CourseSummary(
                course_id=row[0],
                code=row[1],
                name=row[2],
                semester=row[3],
                teacher_id=row[4],
            )
            for row in rows
        }

    async def is_enrolled(self, course_id: UUID, student_id: UUID) -> bool:
        hit = (
            await self._session.execute(
                select(EnrollmentModel.id).where(
                    EnrollmentModel.course_id == course_id,
                    EnrollmentModel.student_id == student_id,
                )
            )
        ).scalar_one_or_none()
        return hit is not None
