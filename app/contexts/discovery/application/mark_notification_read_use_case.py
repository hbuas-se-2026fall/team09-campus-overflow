"""通知已读用例（F04）：单条幂等 + 全部已读返回计数。"""

from __future__ import annotations

from uuid import UUID

from app.contexts.discovery.domain.repository import NotificationRepository


class MarkNotificationReadUseCase:
    def __init__(self, repository: NotificationRepository) -> None:
        self._repository = repository

    async def execute(self, notification_id: UUID, recipient_id: UUID) -> bool:
        """False = 通知不存在或不属于该收件人（路由转 404，不泄露存在性）。"""
        return await self._repository.mark_read(notification_id, recipient_id)


class MarkAllNotificationsReadUseCase:
    def __init__(self, repository: NotificationRepository) -> None:
        self._repository = repository

    async def execute(self, recipient_id: UUID) -> int:
        return await self._repository.mark_all_read(recipient_id)
