"""course 上下文领域异常定义。"""

from __future__ import annotations


class CourseDomainError(Exception):
    """course 上下文领域错误基类。"""


class CourseNotFoundError(CourseDomainError):
    """课程不存在（HTTP 404）。"""


class CourseCodeAlreadyExistsError(CourseDomainError):
    """课程编号已存在（HTTP 409）。"""


class AlreadyEnrolledError(CourseDomainError):
    """学生已选修该课程（HTTP 409）。"""


class CoursePermissionDeniedError(CourseDomainError):
    """无权执行当前课程操作（HTTP 403）。"""
