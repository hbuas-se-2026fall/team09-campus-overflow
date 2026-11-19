"""通知用例单测（F04）：分页、未读筛选、已读归属与计数，不连库。"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.contexts.discovery.application.get_unread_count_use_case import (
    GetUnreadCountUseCase,
)
from app.contexts.discovery.application.list_notifications_use_case import (
    ListNotificationsUseCase,
)
from app.contexts.discovery.application.mark_notification_read_use_case import (
    MarkAllNotificationsReadUseCase,
    MarkNotificationReadUseCase,
)
from app.contexts.discovery.domain.notification import (
    Notification,
    NotificationTargetType,
    NotificationType,
)


def _notification(recipient: UUID, *, read: bool, at: datetime) -> Notification:
    return Notification(
        id=uuid4(),
        recipient_id=recipient,
        type=NotificationType.ANSWER_POSTED,
        actor_id=uuid4(),
        target_type=NotificationTargetType.QUESTION,
        target_id=uuid4(),
        source_event_id=uuid4(),
        is_read=read,
        created_at=at,
    )


class FakeRepository:
    def __init__(self, items: list[Notification]) -> None:
        self.items = items

    async def list_paginated(
        self, recipient_id: UUID, page: int, page_size: int, unread_only: bool
    ) -> tuple[list[Notification], int]:
        rows = [
            n
            for n in self.items
            if n.recipient_id == recipient_id and (not unread_only or not n.is_read)
        ]
        rows.sort(key=lambda n: (n.created_at, n.id), reverse=True)
        start = (page - 1) * page_size
        return rows[start : start + page_size], len(rows)

    async def mark_read(self, notification_id: UUID, recipient_id: UUID) -> bool:
        for index, item in enumerate(self.items):
            if item.id == notification_id and item.recipient_id == recipient_id:
                self.items[index] = replace(item, is_read=True)
                return True
        return False

    async def mark_all_read(self, recipient_id: UUID) -> int:
        count = 0
        for index, item in enumerate(self.items):
            if item.recipient_id == recipient_id and not item.is_read:
                self.items[index] = replace(item, is_read=True)
                count += 1
        return count

    async def unread_count(self, recipient_id: UUID) -> int:
        return sum(
            1 for n in self.items if n.recipient_id == recipient_id and not n.is_read
        )


async def test_list_paginates_and_filters_unread() -> None:
    user = uuid4()
    base = datetime(2026, 1, 1, tzinfo=UTC)
    items = [
        _notification(user, read=False, at=base + timedelta(seconds=i))
        for i in range(3)
    ] + [_notification(user, read=True, at=base + timedelta(seconds=9))]
    repo = FakeRepository(items)

    page = await ListNotificationsUseCase(repo).execute(user, 1, 2, True)
    assert page.total == 3
    assert page.total_pages == 2
    assert len(page.items) == 2
    assert all(not n.is_read for n in page.items)

    page2 = await ListNotificationsUseCase(repo).execute(user, 2, 2, True)
    assert len(page2.items) == 1


async def test_list_only_current_recipient() -> None:
    user, other = uuid4(), uuid4()
    repo = FakeRepository([_notification(other, read=False, at=datetime.now(UTC))])
    page = await ListNotificationsUseCase(repo).execute(user, 1, 20, False)
    assert page.total == 0


async def test_mark_read_respects_ownership() -> None:
    user, other = uuid4(), uuid4()
    item = _notification(user, read=False, at=datetime.now(UTC))
    repo = FakeRepository([item])
    assert await MarkNotificationReadUseCase(repo).execute(item.id, other) is False
    assert await MarkNotificationReadUseCase(repo).execute(item.id, user) is True
    assert repo.items[0].is_read is True


async def test_mark_all_read_returns_updated_count_and_is_idempotent() -> None:
    user = uuid4()
    base = datetime.now(UTC)
    repo = FakeRepository(
        [
            _notification(user, read=False, at=base),
            _notification(user, read=False, at=base),
            _notification(user, read=True, at=base),
        ]
    )
    use_case = MarkAllNotificationsReadUseCase(repo)
    assert await use_case.execute(user) == 2
    assert await use_case.execute(user) == 0


async def test_unread_count_matches_rows() -> None:
    user = uuid4()
    base = datetime.now(UTC)
    repo = FakeRepository(
        [
            _notification(user, read=False, at=base),
            _notification(user, read=True, at=base),
        ]
    )
    assert await GetUnreadCountUseCase(repo).execute(user) == 1
