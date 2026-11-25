"""qa 应用层对外端口：通知写入（F04）与课程只读准入（F17）。

签名使用原始类型或本地 DTO，避免跨上下文 domain/infrastructure 耦合（守 A4）。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


class NotificationWriter(Protocol):
    async def write(
        self,
        *,
        recipient_id: UUID,
        type: str,
        actor_id: UUID,
        target_type: str,
        target_id: UUID,
        source_event_id: UUID,
        question_id: UUID | None = None,
    ) -> None:
        """同事务写入一条通知；重复事件由库级唯一约束吸收。"""
        ...


@dataclass(frozen=True, slots=True)
class CourseSummary:
    """F17：qa 上下文消费的课程公开只读摘要。"""

    course_id: UUID
    code: str
    name: str
    semester: str


class CourseAccessReader(Protocol):
    """F17：课程存在性与选课准入只读端口（DIP，由 interfaces 层适配器注入）。"""

    async def get_summary(self, course_id: UUID) -> CourseSummary | None:
        """查询课程摘要；不存在返回 None。"""
        ...

    async def get_summaries(
        self, course_ids: Iterable[UUID]
    ) -> dict[UUID, CourseSummary]:
        """批量查询课程摘要；空集合零 SQL，缺失课程不入字典。"""
        ...

    async def is_enrolled(self, course_id: UUID, student_id: UUID) -> bool:
        """校验学生是否已选修指定课程。"""
        ...
