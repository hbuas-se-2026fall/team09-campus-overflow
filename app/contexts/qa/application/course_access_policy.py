"""F17 单源课程发问/编辑准入校验策略（供 Ask/Edit 用例共用）。"""

from __future__ import annotations

from uuid import UUID

from app.contexts.qa.application.ports import CourseAccessReader
from app.contexts.qa.domain.errors import (
    CourseEnrollmentRequiredError,
    CourseNotFoundError,
)


async def ensure_course_question_access(
    *,
    course_id: UUID | None,
    actor_id: UUID,
    actor_role: str,
    course_reader: CourseAccessReader | None,
) -> None:
    """校验课程存在性及学生选课准入：course_id 为空直接放行，教职/管理员跨课放行。"""
    if course_id is None:
        return
    if course_reader is None:
        raise RuntimeError("CourseAccessReader 未注入")
    summary = await course_reader.get_summary(course_id)
    if summary is None:
        raise CourseNotFoundError("课程不存在")
    if actor_role == "student" and not await course_reader.is_enrolled(
        course_id, actor_id
    ):
        raise CourseEnrollmentRequiredError("仅已选修该课程的学生可在该课程下提问")
