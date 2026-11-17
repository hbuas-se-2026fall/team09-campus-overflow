"""通知持久化端口（F04，discovery）：domain 定义，infrastructure 实现。"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.contexts.discovery.domain.notification import Notification


class NotificationRepository(Protocol):
    async def add(self, notification: Notification) -> None:
        """写入通知；重复事件由唯一索引 ON CONFLICT DO NOTHING 吸收。"""
        ...

    async def list_paginated(
        self,
        recipient_id: UUID,
        page: int,
        page_size: int,
        unread_only: bool,
    ) -> tuple[list[Notification], int]:
        """按收件人分页（created_at 倒序 + id tiebreaker），返回（当前页, total）。"""
        ...

    async def mark_read(self, notification_id: UUID, recipient_id: UUID) -> bool:
        """标记单条已读；返回该通知是否属于该收件人（不存在/他人 → False）。"""
        ...

    async def mark_all_read(self, recipient_id: UUID) -> int:
        """全部标记已读，返回本次由未读转为已读的条数（幂等）。"""
        ...

    async def unread_count(self, recipient_id: UUID) -> int:
        """未读条数。"""
        ...
