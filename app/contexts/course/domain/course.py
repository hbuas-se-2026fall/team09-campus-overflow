"""Course 聚合根。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.contexts.course.domain.value_objects import CourseCode, CourseName, Semester


@dataclass(slots=True)
class Course:
    """课程聚合根：包含唯一课程编号、名称、学期与授课教师引用。"""

    id: UUID
    code: CourseCode
    name: CourseName
    semester: Semester
    teacher_id: UUID
    created_at: datetime

    @classmethod
    def create(
        cls,
        *,
        code: str,
        name: str,
        semester: str,
        teacher_id: UUID,
    ) -> Course:
        return cls(
            id=uuid4(),
            code=CourseCode(code),
            name=CourseName(name),
            semester=Semester(semester),
            teacher_id=teacher_id,
            created_at=datetime.now(UTC),
        )
