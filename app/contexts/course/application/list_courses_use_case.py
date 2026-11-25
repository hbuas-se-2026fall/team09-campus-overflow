"""分页查询课程列表用例。"""

from __future__ import annotations

import math

from app.contexts.course.application.queries import (
    ListCoursesQuery,
    ListCoursesResult,
)
from app.contexts.course.domain.repository import CourseRepository
from app.contexts.course.domain.value_objects import Semester


class ListCoursesUseCase:
    """分页查询课程，支持可选 semester 规范化筛选。"""

    def __init__(self, courses: CourseRepository) -> None:
        self._courses = courses

    async def execute(self, query: ListCoursesQuery) -> ListCoursesResult:
        semester_vo: Semester | None = None
        if query.semester is not None and query.semester.strip():
            semester_vo = Semester(query.semester)
        items, total = await self._courses.list_paginated(
            page=query.page,
            page_size=query.page_size,
            semester=semester_vo,
        )
        return ListCoursesResult(
            items=items,
            total=total,
            page=query.page,
            page_size=query.page_size,
            total_pages=math.ceil(total / query.page_size) if total else 0,
        )
