"""学生选课用例。"""

from __future__ import annotations

from app.contexts.course.application.commands import EnrollCourseCommand
from app.contexts.course.domain.enrollment import Enrollment
from app.contexts.course.domain.errors import CourseNotFoundError
from app.contexts.course.domain.repository import (
    CourseRepository,
    EnrollmentRepository,
)


class EnrollCourseUseCase:
    """学生自助选课：先校验课程存在，再写入选课记录（重复选课由仓储抛 409）。"""

    def __init__(
        self,
        courses: CourseRepository,
        enrollments: EnrollmentRepository,
    ) -> None:
        self._courses = courses
        self._enrollments = enrollments

    async def execute(self, command: EnrollCourseCommand) -> Enrollment:
        course = await self._courses.get_by_id(command.course_id)
        if course is None:
            raise CourseNotFoundError("课程不存在")
        enrollment = Enrollment.enroll(
            course_id=course.id,
            student_id=command.student_id,
        )
        await self._enrollments.add(enrollment)
        return enrollment
