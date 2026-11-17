"""qa 应用层对外端口（F04）：通知写入。

签名使用原始类型，discovery 适配器结构化匹配即可（零 import qa），
mypy 结构类型 + CI 类型门禁兜底签名漂移。
"""

from __future__ import annotations

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
