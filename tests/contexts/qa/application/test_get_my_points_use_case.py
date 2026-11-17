"""个人积分查询用例单测（F07 闭环）：教师惰性开户 / 学生只读 / 流水透传。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.contexts.qa.application.get_my_points_use_case import GetMyPointsUseCase
from app.contexts.qa.domain.bounty import INITIAL_TEACHER_POINTS, PointsEntry


class FakePointsRepository:
    def __init__(self) -> None:
        self.balances: dict[UUID, int] = {}
        self.entries_by_user: dict[UUID, list[PointsEntry]] = {}
        self.ensure_calls: list[UUID] = []

    async def ensure_teacher_account(self, user_id: UUID) -> int:
        self.ensure_calls.append(user_id)
        if user_id not in self.balances:
            self.balances[user_id] = INITIAL_TEACHER_POINTS
            self.entries_by_user.setdefault(user_id, []).append(
                PointsEntry(
                    source="grant",
                    event_id=user_id,
                    delta=INITIAL_TEACHER_POINTS,
                    reason="教师初始积分",
                    occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
                )
            )
        return self.balances[user_id]

    async def deduct(self, user_id: UUID, amount: int) -> bool:
        return False

    async def credit(self, user_id: UUID, amount: int) -> None:
        return None

    async def append(self, user_id: UUID, entry: PointsEntry) -> bool:
        return True

    async def balance(self, user_id: UUID) -> int:
        return self.balances.get(user_id, 0)

    async def list_entries(self, user_id: UUID) -> list[PointsEntry]:
        return list(self.entries_by_user.get(user_id, []))


async def test_teacher_gets_lazy_initial_points_and_entries() -> None:
    repo = FakePointsRepository()
    teacher = uuid4()
    view = await GetMyPointsUseCase(repo).execute(teacher, "teacher")

    assert repo.ensure_calls == [teacher]
    assert view.balance == INITIAL_TEACHER_POINTS
    assert len(view.entries) == 1
    assert view.entries[0].source == "grant"
    assert view.entries[0].delta == INITIAL_TEACHER_POINTS


async def test_student_reads_existing_balance_without_teacher_grant() -> None:
    repo = FakePointsRepository()
    student = uuid4()
    award = PointsEntry(
        source="bounty_award",
        event_id=uuid4(),
        delta=30,
        reason="悬赏结算",
        occurred_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    repo.balances[student] = 30
    repo.entries_by_user[student] = [award]

    view = await GetMyPointsUseCase(repo).execute(student, "student")
    assert repo.ensure_calls == []
    assert view.balance == 30
    assert view.entries == [award]


async def test_student_without_account_returns_zero_and_empty_entries() -> None:
    repo = FakePointsRepository()
    view = await GetMyPointsUseCase(repo).execute(uuid4(), "student")
    assert view.balance == 0
    assert view.entries == []
