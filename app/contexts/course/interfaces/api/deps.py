"""course 组合根：仓储、用例与跨上下文端口唯一装配处。"""

from __future__ import annotations

from typing import Annotated, Protocol
from uuid import UUID

from fastapi import Depends

from app.contexts.course.application.create_course_use_case import CreateCourseUseCase
from app.contexts.course.application.enroll_course_use_case import EnrollCourseUseCase
from app.contexts.course.application.list_course_students_use_case import (
    ListCourseStudentsUseCase,
)
from app.contexts.course.application.list_courses_use_case import ListCoursesUseCase
from app.contexts.course.application.ports import CourseAccessReader
from app.contexts.course.domain.repository import (
    CourseRepository,
    EnrollmentRepository,
)
from app.contexts.course.infrastructure.course_access_reader import (
    SqlAlchemyCourseAccessReader,
)
from app.contexts.course.infrastructure.course_repository import (
    SqlAlchemyCourseRepository,
)
from app.contexts.course.infrastructure.enrollment_repository import (
    SqlAlchemyEnrollmentRepository,
)
from app.contexts.identity.interfaces.api.deps import (
    UserSummaryReaderDep,
    require_roles,
)
from app.platform.http.deps import SessionDep


class AuthenticatedUser(Protocol):
    """当前登录用户最小结构契约（不直接 import identity.domain，守 A4）。"""

    @property
    def id(self) -> UUID: ...

    @property
    def role(self) -> str: ...

    @property
    def display_name(self) -> str: ...


def get_course_repository(session: SessionDep) -> CourseRepository:
    return SqlAlchemyCourseRepository(session)


def get_enrollment_repository(session: SessionDep) -> EnrollmentRepository:
    return SqlAlchemyEnrollmentRepository(session)


def get_course_access_reader(session: SessionDep) -> CourseAccessReader:
    """公开供给面：供下游上下文（如 F17 qa）只读查询课程摘要与选课准入。"""
    return SqlAlchemyCourseAccessReader(session)


def build_create_course_use_case(courses: CourseRepository) -> CreateCourseUseCase:
    return CreateCourseUseCase(courses)


def build_list_courses_use_case(courses: CourseRepository) -> ListCoursesUseCase:
    return ListCoursesUseCase(courses)


def build_enroll_course_use_case(
    courses: CourseRepository,
    enrollments: EnrollmentRepository,
) -> EnrollCourseUseCase:
    return EnrollCourseUseCase(courses, enrollments)


def build_list_course_students_use_case(
    courses: CourseRepository,
    enrollments: EnrollmentRepository,
) -> ListCourseStudentsUseCase:
    return ListCourseStudentsUseCase(courses, enrollments)


CourseRepo = Annotated[CourseRepository, Depends(get_course_repository)]
EnrollmentRepo = Annotated[EnrollmentRepository, Depends(get_enrollment_repository)]
CourseAccessReaderDep = Annotated[
    CourseAccessReader, Depends(get_course_access_reader)
]

CourseCreatorUser = Annotated[
    AuthenticatedUser, Depends(require_roles("teacher", "admin"))
]
StudentUser = Annotated[AuthenticatedUser, Depends(require_roles("student"))]
CourseStaffUser = Annotated[
    AuthenticatedUser, Depends(require_roles("teacher", "ta", "admin"))
]

__all__ = [
    "AuthenticatedUser",
    "CourseAccessReaderDep",
    "CourseCreatorUser",
    "CourseRepo",
    "CourseStaffUser",
    "EnrollmentRepo",
    "StudentUser",
    "UserSummaryReaderDep",
    "build_create_course_use_case",
    "build_enroll_course_use_case",
    "build_list_course_students_use_case",
    "build_list_courses_use_case",
    "get_course_access_reader",
    "get_course_repository",
    "get_enrollment_repository",
]
