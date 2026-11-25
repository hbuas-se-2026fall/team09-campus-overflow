"""course 上下文仓储端口协议。"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.contexts.course.domain.course import Course
from app.contexts.course.domain.enrollment import Enrollment
from app.contexts.course.domain.value_objects import Semester


class CourseRepository(Protocol):
    """课程聚合持久化端口。"""

    async def add(self, course: Course) -> None:
        """持久化新建课程；课程编号冲突时抛出 CourseCodeAlreadyExistsError。"""
        ...

    async def get_by_id(self, course_id: UUID) -> Course | None:
        """按 ID 查询课程；不存在返回 None。"""
        ...

    async def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        semester: Semester | None = None,
    ) -> tuple[list[Course], int]:
        """分页查询课程列表并返回总数（COUNT 与列表同口径）。"""
        ...


class EnrollmentRepository(Protocol):
    """选课聚合持久化端口。"""

    async def add(self, enrollment: Enrollment) -> None:
        """持久化选课记录；重复选课抛 AlreadyEnrolledError，课程不存在抛 CourseNotFoundError。"""
        ...

    async def exists(self, course_id: UUID, student_id: UUID) -> bool:
        """判断学生是否已选修指定课程。"""
        ...

    async def list_by_course_paginated(
        self,
        course_id: UUID,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[Enrollment], int]:
        """分页查询指定课程的选课记录并返回总数。"""
        ...
