"""通知仓储实现（F04）：ON CONFLICT 幂等写入 + 分页 + 已读。"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.discovery.domain.notification import (
    Notification,
    NotificationTargetType,
    NotificationType,
)
from app.contexts.discovery.infrastructure.models import NotificationModel


def _parse_question_id(payload: object) -> UUID | None:
    if not isinstance(payload, dict):
        return None
    raw = payload.get("question_id")
    if not isinstance(raw, str):
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


def _to_domain(model: NotificationModel) -> Notification:
    return Notification(
        id=model.id,
        recipient_id=model.recipient_id,
        type=NotificationType(model.type),
        actor_id=model.actor_id,
        target_type=NotificationTargetType(model.target_type),
        target_id=model.target_id,
        source_event_id=model.source_event_id,
        is_read=model.is_read,
        created_at=model.created_at,
        question_id=_parse_question_id(model.payload),
    )


class SqlAlchemyNotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, notification: Notification) -> None:
        payload = (
            {"question_id": str(notification.question_id)}
            if notification.question_id is not None
            else {}
        )
        stmt = (
            insert(NotificationModel)
            .values(
                id=notification.id,
                recipient_id=notification.recipient_id,
                type=notification.type.value,
                actor_id=notification.actor_id,
                target_type=notification.target_type.value,
                target_id=notification.target_id,
                source_event_id=notification.source_event_id,
                payload=payload,
                is_read=notification.is_read,
                created_at=notification.created_at,
            )
            .on_conflict_do_nothing(
                index_elements=["type", "source_event_id", "recipient_id"]
            )
        )
        await self._session.execute(stmt)

    async def list_paginated(
        self,
        recipient_id: UUID,
        page: int,
        page_size: int,
        unread_only: bool,
    ) -> tuple[list[Notification], int]:
        conditions = [NotificationModel.recipient_id == recipient_id]
        if unread_only:
            conditions.append(NotificationModel.is_read.is_(False))
        total = (
            await self._session.execute(
                select(func.count()).select_from(NotificationModel).where(*conditions)
            )
        ).scalar_one()
        stmt = (
            select(NotificationModel)
            .where(*conditions)
            .order_by(
                NotificationModel.created_at.desc(), NotificationModel.id.desc()
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        models = (await self._session.execute(stmt)).scalars().all()
        return [_to_domain(m) for m in models], int(total)

    async def mark_read(self, notification_id: UUID, recipient_id: UUID) -> bool:
        stmt = (
            update(NotificationModel)
            .where(
                NotificationModel.id == notification_id,
                NotificationModel.recipient_id == recipient_id,
            )
            .values(is_read=True)
            .returning(NotificationModel.id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def mark_all_read(self, recipient_id: UUID) -> int:
        stmt = (
            update(NotificationModel)
            .where(
                NotificationModel.recipient_id == recipient_id,
                NotificationModel.is_read.is_(False),
            )
            .values(is_read=True)
            .returning(NotificationModel.id)
        )
        return len((await self._session.execute(stmt)).scalars().all())

    async def unread_count(self, recipient_id: UUID) -> int:
        result = await self._session.execute(
            select(func.count())
            .select_from(NotificationModel)
            .where(
                NotificationModel.recipient_id == recipient_id,
                NotificationModel.is_read.is_(False),
            )
        )
        return int(result.scalar_one())
