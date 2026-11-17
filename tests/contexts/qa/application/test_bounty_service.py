"""悬赏服务单测（F07）：冻结、余额不足、结算/退款只一次，不连库。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.contexts.qa.application.bounty_service import BountyService
from app.contexts.qa.domain.bounty import Bounty, BountyStatus, PointsEntry
from app.contexts.qa.domain.errors import (
    BountyAlreadyActiveError,
    InsufficientPointsError,
)


class FakePointsRepository:
    def __init__(self, balance: int = 100) -> None:
        self.balances: dict[UUID, int] = {}
        self.entries: list[tuple[UUID, PointsEntry]] = []
        self.default_balance = balance

    async def ensure_teacher_account(self, user_id: UUID) -> int:
        self.balances.setdefault(user_id, self.default_balance)
        return self.balances[user_id]

    async def deduct(self, user_id: UUID, amount: int) -> bool:
        current = self.balances.get(user_id, 0)
        if current < amount:
            return False
        self.balances[user_id] = current - amount
        return True

    async def credit(self, user_id: UUID, amount: int) -> None:
        self.balances[user_id] = self.balances.get(user_id, 0) + amount

    async def append(self, user_id: UUID, entry: PointsEntry) -> bool:
        self.entries.append((user_id, entry))
        return True

    async def balance(self, user_id: UUID) -> int:
        return self.balances.get(user_id, 0)

    async def list_entries(self, user_id: UUID) -> list[PointsEntry]:
        return [entry for uid, entry in self.entries if uid == user_id]


class FakeBountyRepository:
    def __init__(self) -> None:
        self.bounties: dict[UUID, Bounty] = {}
        self.fail_add = False

    async def add(self, bounty: Bounty) -> None:
        if self.fail_add:
            raise BountyAlreadyActiveError("该问题已有进行中的悬赏")
        self.bounties[bounty.question_id] = bounty

    async def get_active(self, question_id: UUID) -> Bounty | None:
        bounty = self.bounties.get(question_id)
        return bounty if bounty is not None and bounty.status is BountyStatus.OPEN else None

    def _transition(self, question_id: UUID, status: BountyStatus) -> Bounty | None:
        bounty = self.bounties.get(question_id)
        if bounty is None or bounty.status is not BountyStatus.OPEN:
            return None
        updated = Bounty(
            id=bounty.id,
            question_id=bounty.question_id,
            teacher_id=bounty.teacher_id,
            amount=bounty.amount,
            status=status,
            created_at=bounty.created_at,
            settled_at=datetime.now(UTC),
        )
        self.bounties[question_id] = updated
        return updated

    async def settle(self, question_id: UUID) -> Bounty | None:
        return self._transition(question_id, BountyStatus.SETTLED)

    async def refund(self, question_id: UUID) -> Bounty | None:
        return self._transition(question_id, BountyStatus.REFUNDED)


async def test_create_freezes_points_and_writes_ledger() -> None:
    points = FakePointsRepository(balance=100)
    bounties = FakeBountyRepository()
    service = BountyService(bounties, points)
    teacher = uuid4()
    question = uuid4()

    bounty = await service.create(question, teacher, 30)

    assert bounty.status is BountyStatus.OPEN
    assert points.balances[teacher] == 70
    assert len(points.entries) == 1
    entry = points.entries[0][1]
    assert entry.source == "bounty"
    assert entry.delta == -30


async def test_create_rejects_insufficient_points() -> None:
    service = BountyService(FakeBountyRepository(), FakePointsRepository(balance=10))
    with pytest.raises(InsufficientPointsError):
        await service.create(uuid4(), uuid4(), 11)


async def test_duplicate_active_bounty_raises() -> None:
    bounties = FakeBountyRepository()
    bounties.fail_add = True
    service = BountyService(bounties, FakePointsRepository(balance=100))
    with pytest.raises(BountyAlreadyActiveError):
        await service.create(uuid4(), uuid4(), 10)


async def test_settle_credits_answer_author_once() -> None:
    bounties = FakeBountyRepository()
    points = FakePointsRepository(balance=100)
    service = BountyService(bounties, points)
    teacher, answer_author, question = uuid4(), uuid4(), uuid4()
    await service.create(question, teacher, 40)

    assert await service.settle_on_accept(question, answer_author) is True
    assert points.balances[answer_author] == 40
    assert await service.settle_on_accept(question, answer_author) is False
    assert points.balances[answer_author] == 40


async def test_refund_returns_points_to_teacher_once() -> None:
    bounties = FakeBountyRepository()
    points = FakePointsRepository(balance=100)
    service = BountyService(bounties, points)
    teacher, question = uuid4(), uuid4()
    await service.create(question, teacher, 25)

    assert await service.refund_on_close(question) is True
    assert points.balances[teacher] == 100
    assert await service.refund_on_close(question) is False
    assert points.balances[teacher] == 100
