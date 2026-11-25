"""创建课程用例。"""

from __future__ import annotations

from app.contexts.course.application.commands import CreateCourseCommand
from app.contexts.course.domain.course import Course
from app.contexts.course.domain.repository import CourseRepository


class CreateCourseUseCase:
    """创建课程并将课程编号唯一性冲突交由仓储转译为领域异常。"""

    def __init__(self, courses: CourseRepository) -> None:
        self._courses = courses

    async def execute(self, command: CreateCourseCommand) -> Course:
        course = Course.create(
            code=command.code,
            name=command.name,
            semester=command.semester,
            teacher_id=command.actor_id,
        )
        await self._courses.add(course)
        return course
