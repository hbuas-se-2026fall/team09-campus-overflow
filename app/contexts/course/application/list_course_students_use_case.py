"""分页查询课程选课学生用例。"""

from __future__ import annotations

import math

from app.contexts.course.application.queries import (
    ListCourseStudentsQuery,
    ListCourseStudentsResult,
)
from app.contexts.course.domain.errors import CourseNotFoundError
from app.contexts.course.domain.repository import (
    CourseRepository,
    EnrollmentRepository,
)


class ListCourseStudentsUseCase:
    """分页查询课程已选学生：先校验课程存在，再返回同口径分页结果。"""

    def __init__(
        self,
        courses: CourseRepository,
        enrollments: EnrollmentRepository,
    ) -> None:
        self._courses = courses
        self._enrollments = enrollments

    async def execute(
        self, query: ListCourseStudentsQuery
    ) -> ListCourseStudentsResult:
        course = await self._courses.get_by_id(query.course_id)
        if course is None:
            raise CourseNotFoundError("课程不存在")
        items, total = await self._enrollments.list_by_course_paginated(
            query.course_id,
            page=query.page,
            page_size=query.page_size,
        )
        return ListCourseStudentsResult(
            items=items,
            total=total,
            page=query.page,
            page_size=query.page_size,
            total_pages=math.ceil(total / query.page_size) if total else 0,
        )
