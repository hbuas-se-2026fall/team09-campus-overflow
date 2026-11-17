"""通知列表用例（F04）：分页 + 未读筛选。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from uuid import UUID

from app.contexts.discovery.domain.notification import Notification
from app.contexts.discovery.domain.repository import NotificationRepository


@dataclass(frozen=True, slots=True)
class NotificationPage:
    items: list[Notification]
    total: int
    page: int
    page_size: int
    total_pages: int


class ListNotificationsUseCase:
    def __init__(self, repository: NotificationRepository) -> None:
        self._repository = repository

    async def execute(
        self,
        recipient_id: UUID,
        page: int,
        page_size: int,
        unread_only: bool,
    ) -> NotificationPage:
        items, total = await self._repository.list_paginated(
            recipient_id, page, page_size, unread_only
        )
        return NotificationPage(
            items=items,
            total=total,
            page=page,
            page_size=page_size,
            total_pages=math.ceil(total / page_size) if total else 0,
        )
