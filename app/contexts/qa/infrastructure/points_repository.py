"""积分仓储实现（F07/D12）：惰性开户 + 条件扣减 + 入账 + 幂等流水。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.qa.domain.bounty import INITIAL_TEACHER_POINTS, PointsEntry
from app.contexts.qa.infrastructure.models import PointLedgerModel, PointsAccountModel


class SqlAlchemyPointsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _ensure_account(self, user_id: UUID, initial_balance: int) -> bool:
        stmt = (
            insert(PointsAccountModel)
            .values(user_id=user_id, balance=initial_balance)
            .on_conflict_do_nothing(index_elements=["user_id"])
            .returning(PointsAccountModel.user_id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def ensure_teacher_account(self, user_id: UUID) -> int:
        inserted = await self._ensure_account(user_id, INITIAL_TEACHER_POINTS)
        if inserted:
            await self.append(
                user_id,
                PointsEntry(
                    source="grant",
                    event_id=user_id,
                    delta=INITIAL_TEACHER_POINTS,
                    reason="教师初始积分",
                    occurred_at=datetime.now(UTC),
                ),
            )
        return await self.balance(user_id)

    async def deduct(self, user_id: UUID, amount: int) -> bool:
        stmt = (
            update(PointsAccountModel)
            .where(
                PointsAccountModel.user_id == user_id,
                PointsAccountModel.balance >= amount,
            )
            .values(balance=PointsAccountModel.balance - amount)
            .returning(PointsAccountModel.user_id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def credit(self, user_id: UUID, amount: int) -> None:
        await self._ensure_account(user_id, 0)
        await self._session.execute(
            update(PointsAccountModel)
            .where(PointsAccountModel.user_id == user_id)
            .values(balance=PointsAccountModel.balance + amount)
        )

    async def append(self, user_id: UUID, entry: PointsEntry) -> bool:
        stmt = (
            insert(PointLedgerModel)
            .values(
                id=uuid4(),
                user_id=user_id,
                source=entry.source,
                event_id=entry.event_id,
                delta=entry.delta,
                reason=entry.reason,
                occurred_at=entry.occurred_at,
            )
            .on_conflict_do_nothing(index_elements=["source", "event_id"])
            .returning(PointLedgerModel.id)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

    async def balance(self, user_id: UUID) -> int:
        value = (
            await self._session.execute(
                select(PointsAccountModel.balance).where(
                    PointsAccountModel.user_id == user_id
                )
            )
        ).scalar_one_or_none()
        return int(value or 0)

    async def list_entries(self, user_id: UUID) -> list[PointsEntry]:
        rows = (
            await self._session.execute(
                select(PointLedgerModel)
                .where(PointLedgerModel.user_id == user_id)
                .order_by(
                    PointLedgerModel.occurred_at.desc(),
                    PointLedgerModel.id.desc(),
                )
            )
        ).scalars().all()
        return [
            PointsEntry(
                source=row.source,
                event_id=row.event_id,
                delta=row.delta,
                reason=row.reason,
                occurred_at=row.occurred_at,
            )
            for row in rows
        ]
