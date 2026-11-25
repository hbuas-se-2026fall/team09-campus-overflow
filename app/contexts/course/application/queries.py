"""course 上下文只读查询 DTO 与分页结果。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.contexts.course.domain.course import Course
from app.contexts.course.domain.enrollment import Enrollment


@dataclass(frozen=True, slots=True)
class ListCoursesQuery:
    """分页查询课程列表参数。"""

    page: int = 1
    page_size: int = 20
    semester: str | None = None


@dataclass(frozen=True, slots=True)
class ListCoursesResult:
    """课程列表分页结果（total_pages = ceil(total/page_size)，空库为 0）。"""

    items: list[Course]
    total: int
    page: int
    page_size: int
    total_pages: int


@dataclass(frozen=True, slots=True)
class ListCourseStudentsQuery:
    """分页查询课程选课学生列表参数。"""

    course_id: UUID
    page: int = 1
    page_size: int = 20


@dataclass(frozen=True, slots=True)
class ListCourseStudentsResult:
    """课程选课学生列表分页结果（total_pages = ceil(total/page_size)，空库为 0）。"""

    items: list[Enrollment]
    total: int
    page: int
    page_size: int
    total_pages: int
