"""course 领域错误 → HTTP 状态码的唯一映射（interfaces 层）。"""

from __future__ import annotations

from fastapi import FastAPI, status

from app.contexts.course.domain.errors import (
    AlreadyEnrolledError,
    CourseCodeAlreadyExistsError,
    CourseDomainError,
    CourseNotFoundError,
    CoursePermissionDeniedError,
)
from app.platform.http.error_mapping import make_domain_error_handler

COURSE_ERROR_STATUS: dict[type[Exception], int] = {
    CourseNotFoundError: status.HTTP_404_NOT_FOUND,
    CourseCodeAlreadyExistsError: status.HTTP_409_CONFLICT,
    AlreadyEnrolledError: status.HTTP_409_CONFLICT,
    CoursePermissionDeniedError: status.HTTP_403_FORBIDDEN,
    CourseDomainError: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def register_course_error_handlers(application: FastAPI) -> None:
    for exc_type, status_code in COURSE_ERROR_STATUS.items():
        application.add_exception_handler(
            exc_type, make_domain_error_handler(status_code)
        )
