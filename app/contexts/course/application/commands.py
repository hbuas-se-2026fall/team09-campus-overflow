"""course 上下文写用例命令 DTO。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CreateCourseCommand:
    """创建课程命令。"""

    actor_id: UUID
    code: str
    name: str
    semester: str


@dataclass(frozen=True, slots=True)
class EnrollCourseCommand:
    """学生选课命令。"""

    course_id: UUID
    student_id: UUID
