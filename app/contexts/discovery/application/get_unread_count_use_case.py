"""未读数用例（F04）。"""

from __future__ import annotations

from uuid import UUID

from app.contexts.discovery.domain.repository import NotificationRepository


class GetUnreadCountUseCase:
    def __init__(self, repository: NotificationRepository) -> None:
        self._repository = repository

    async def execute(self, recipient_id: UUID) -> int:
        return await self._repository.unread_count(recipient_id)
