"""通知仓储集成测试（F04）：唯一约束幂等、分页/未读、已读归属与计数。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.contexts.discovery.domain.notification import (
    Notification,
    NotificationTargetType,
    NotificationType,
)
from app.contexts.discovery.infrastructure.notification_repository import (
    SqlAlchemyNotificationRepository,
)
from app.contexts.identity.application.commands import RegisterCommand
from app.contexts.identity.application.register_use_case import RegisterUseCase
from app.contexts.identity.infrastructure.password_hasher import BcryptPasswordHasher
from app.contexts.identity.infrastructure.repository import SqlAlchemyUserRepository
from app.shared.engine import session_factory

pytestmark = pytest.mark.integration


async def _make_user() -> uuid.UUID:
    async with session_factory() as session:
        use_case = RegisterUseCase(SqlAlchemyUserRepository(session), BcryptPasswordHasher())
        user = await use_case.execute(
            RegisterCommand(
                role="student",
                email=f"{uuid.uuid4()}@stu.edu.cn",
                password="Passw0rd8",
                student_id=str(uuid.uuid4().int)[:10],
            )
        )
        await session.commit()
        return user.id


def _notification(
    recipient: uuid.UUID,
    actor: uuid.UUID,
    *,
    source_event_id: uuid.UUID | None = None,
    at: datetime | None = None,
    question_id: uuid.UUID | None = None,
) -> Notification:
    return Notification(
        id=uuid.uuid4(),
        recipient_id=recipient,
        type=NotificationType.ANSWER_POSTED,
        actor_id=actor,
        target_type=NotificationTargetType.QUESTION,
        target_id=uuid.uuid4(),
        source_event_id=source_event_id or uuid.uuid4(),
        is_read=False,
        created_at=at or datetime.now(UTC),
        question_id=question_id,
    )


async def test_add_is_idempotent_per_event_and_recipient() -> None:
    recipient = await _make_user()
    actor = await _make_user()
    event_id = uuid.uuid4()
    async with session_factory() as session:
        repo = SqlAlchemyNotificationRepository(session)
        await repo.add(_notification(recipient, actor, source_event_id=event_id))
        await repo.add(_notification(recipient, actor, source_event_id=event_id))
        await session.commit()
        items, total = await repo.list_paginated(recipient, 1, 20, False)
        assert total == 1
        assert len(items) == 1


async def test_list_paginates_unread_and_orders_desc() -> None:
    recipient = await _make_user()
    actor = await _make_user()
    base = datetime.now(UTC)
    async with session_factory() as session:
        repo = SqlAlchemyNotificationRepository(session)
        first = _notification(recipient, actor, at=base - timedelta(minutes=1))
        second = _notification(recipient, actor, at=base)
        await repo.add(first)
        await repo.add(second)
        await session.commit()
        await repo.mark_read(first.id, recipient)

        items, total = await repo.list_paginated(recipient, 1, 1, False)
        assert total == 2
        assert [n.id for n in items] == [second.id]
        unread, unread_total = await repo.list_paginated(recipient, 1, 20, True)
        assert unread_total == 1
        assert [n.id for n in unread] == [second.id]


async def test_mark_read_ownership_and_idempotency() -> None:
    recipient = await _make_user()
    other = await _make_user()
    actor = await _make_user()
    async with session_factory() as session:
        repo = SqlAlchemyNotificationRepository(session)
        item = _notification(recipient, actor)
        await repo.add(item)
        await session.commit()

        assert await repo.mark_read(item.id, other) is False
        assert await repo.mark_read(item.id, recipient) is True
        assert await repo.mark_read(item.id, recipient) is True  # 幂等
        assert await repo.unread_count(recipient) == 0


async def test_mark_all_read_returns_updated_count() -> None:
    recipient = await _make_user()
    actor = await _make_user()
    async with session_factory() as session:
        repo = SqlAlchemyNotificationRepository(session)
        for _ in range(2):
            await repo.add(_notification(recipient, actor))
        await session.commit()

        assert await repo.mark_all_read(recipient) == 2
        assert await repo.mark_all_read(recipient) == 0
        assert await repo.unread_count(recipient) == 0


async def test_question_id_payload_roundtrip_and_missing_defaults_none() -> None:
    recipient = await _make_user()
    actor = await _make_user()
    qid = uuid.uuid4()
    async with session_factory() as session:
        repo = SqlAlchemyNotificationRepository(session)
        with_qid = _notification(recipient, actor, question_id=qid)
        without_qid = _notification(recipient, actor, question_id=None)
        await repo.add(with_qid)
        await repo.add(without_qid)
        await session.commit()

        items, total = await repo.list_paginated(recipient, 1, 20, False)
        assert total == 2
        by_id = {n.id: n for n in items}
        assert by_id[with_qid.id].question_id == qid
        assert by_id[without_qid.id].question_id is None
