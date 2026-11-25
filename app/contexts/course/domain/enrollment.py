"""Enrollment 聚合根。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4


@dataclass(slots=True)
class Enrollment:
    """选课记录聚合根：表示学生在某门课程中的唯一选课关系。"""

    id: UUID
    course_id: UUID
    student_id: UUID
    enrolled_at: datetime

    @classmethod
    def enroll(
        cls,
        *,
        course_id: UUID,
        student_id: UUID,
    ) -> Enrollment:
        return cls(
            id=uuid4(),
            course_id=course_id,
            student_id=student_id,
            enrolled_at=datetime.now(UTC),
        )
