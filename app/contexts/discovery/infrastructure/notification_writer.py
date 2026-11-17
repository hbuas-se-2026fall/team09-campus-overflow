"""通知写入适配器（F04）：qa 用例经 NotificationWriter 端口调用，同一 session 同事务。

本模块零 import qa——与 qa 端口仅结构化匹配（reputation DTO 先例同模式）。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.discovery.domain.notification import build_notification
from app.contexts.discovery.infrastructure.notification_repository import (
    SqlAlchemyNotificationRepository,
)


class SqlAlchemyNotificationWriter:
    def __init__(self, session: AsyncSession) -> None:
        self._repository = SqlAlchemyNotificationRepository(session)

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
        await self._repository.add(
            build_notification(
                recipient_id=recipient_id,
                type=type,
                actor_id=actor_id,
                target_type=target_type,
                target_id=target_id,
                source_event_id=source_event_id,
                question_id=question_id,
            )
        )
