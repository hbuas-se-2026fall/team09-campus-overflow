"""course 上下文已发布语言：供下游上下文（如 F17 qa）只读查询课程摘要与选课准入。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CourseSummary:
    """课程公开只读摘要 DTO（不包含写操作或内部实现细节）。"""

    course_id: UUID
    code: str
    name: str
    semester: str
    teacher_id: UUID


class CourseAccessReader(Protocol):
    """跨上下文课程准入与摘要读取窄端口（ISP/CRP）。"""

    async def get_summary(self, course_id: UUID) -> CourseSummary | None:
        """按课程 ID 读取公开摘要；课程不存在返回 None。"""
        ...

    async def get_summaries(
        self, course_ids: Iterable[UUID]
    ) -> dict[UUID, CourseSummary]:
        """按课程 ID 集合批量读取公开摘要；空集合零 SQL，缺失课程不入字典。"""
        ...

    async def is_enrolled(self, course_id: UUID, student_id: UUID) -> bool:
        """校验学生是否已选修指定课程。"""
        ...
