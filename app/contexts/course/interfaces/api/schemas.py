"""course 上下文 HTTP 请求与响应 Schema。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from app.shared.text_validation import reject_unsafe_text

_COURSE_FIELD_LABELS = {
    "code": "课程编号",
    "name": "课程名称",
    "semester": "学期",
}


class CreateCourseRequest(BaseModel):
    """POST /api/v1/courses 请求体。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(min_length=2, max_length=32)
    name: str = Field(min_length=2, max_length=100)
    semester: str = Field(min_length=2, max_length=32)

    @field_validator("code", "name", "semester")
    @classmethod
    def _reject_unsafe_chars(cls, value: str, info: ValidationInfo) -> str:
        label = _COURSE_FIELD_LABELS.get(info.field_name or "", "课程信息")
        reject_unsafe_text(value, field_name=label)
        return value


class CourseResponse(BaseModel):
    """课程响应白名单。"""

    id: UUID
    code: str
    name: str
    semester: str
    teacher_id: UUID
    teacher_name: str
    created_at: datetime


class CourseListResponse(BaseModel):
    """课程列表分页响应。"""

    items: list[CourseResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class EnrollmentResponse(BaseModel):
    """选课成功响应白名单。"""

    id: UUID
    course_id: UUID
    student_id: UUID
    student_name: str
    enrolled_at: datetime


class CourseStudentItem(BaseModel):
    """课程选课学生条目（最小披露：不含邮箱/学工号/密码哈希）。"""

    student_id: UUID
    student_name: str
    enrolled_at: datetime


class CourseStudentListResponse(BaseModel):
    """课程选课学生列表分页响应。"""

    items: list[CourseStudentItem]
    total: int
    page: int
    page_size: int
    total_pages: int
