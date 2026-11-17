"""ReputationLedger 仓储实现（分支 4）：ON CONFLICT 幂等 + SUM 总值 + 倒序流水。"""

from __future__ import annotations

import uuid
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.reputation.domain.leaderboard import LeaderboardRow
from app.contexts.reputation.domain.ledger import LedgerEntry, LedgerSource
from app.contexts.reputation.infrastructure.models import ReputationLedgerModel


class SqlAlchemyReputationLedgerRepository:
    """ReputationLedgerRepository 端口实现。

    append_if_absent 用 PG ON CONFLICT DO NOTHING（而不是"先查后插"）：
    同一事件并发双投递时两事务各持唯一索引判断窗口，先查后插会双双通过检查
    再双双插入撞索引——ON CONFLICT 在 SQL 层原子判定，恰好落一行、
    无异常抛出（rowcount 判定），排除 acks_late 下"报错→重投"循环。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def append_if_absent(self, user_id: UUID, entry: LedgerEntry) -> bool:
        """幂等追加：同 (source, event_id) 已存在时不写并返回 False。

        RETURNING 仅在实际插入行时返回 id——冲突被跳过时结果为空，
        以此判定写入与否（无 rowcount 类型妥协）。
        """
        stmt = (
            insert(ReputationLedgerModel)
            .values(
                id=uuid.uuid4(),
                user_id=user_id,
                source=entry.source.value,
                event_id=entry.event_id,
                delta=entry.delta,
                reason=entry.reason,
                occurred_at=entry.occurred_at,
            )
            .on_conflict_do_nothing(index_elements=["source", "event_id"])
            .returning(ReputationLedgerModel.id)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def total(self, user_id: UUID) -> int:
        """账面声誉值 = SUM(delta)（无流水 0；可为负）。"""
        result = await self._session.execute(
            select(func.coalesce(func.sum(ReputationLedgerModel.delta), 0)).where(
                ReputationLedgerModel.user_id == user_id
            )
        )
        return int(result.scalar_one())

    async def entries_desc(self, user_id: UUID) -> list[LedgerEntry]:
        """流水按 occurred_at 倒序；同刻事件以 id 作确定性 tiebreaker。"""
        rows = await self._session.execute(
            select(ReputationLedgerModel)
            .where(ReputationLedgerModel.user_id == user_id)
            .order_by(
                ReputationLedgerModel.occurred_at.desc(), ReputationLedgerModel.id.desc()
            )
        )
        return [
            LedgerEntry(
                source=LedgerSource(row.source),
                event_id=row.event_id,
                delta=row.delta,
                reason=row.reason,
                occurred_at=row.occurred_at,
            )
            for row in rows.scalars()
        ]

    async def list_top(
        self, start: datetime, end: datetime, limit: int
    ) -> list[LeaderboardRow]:
        """F05：期间 [start, end) 按用户汇总 delta，RANK() 同分同名次（D9）。"""
        score = func.coalesce(func.sum(ReputationLedgerModel.delta), 0)
        rank = func.rank().over(order_by=score.desc())
        stmt = (
            select(
                ReputationLedgerModel.user_id,
                score.label("score"),
                rank.label("rank"),
            )
            .where(
                ReputationLedgerModel.occurred_at >= start,
                ReputationLedgerModel.occurred_at < end,
            )
            .group_by(ReputationLedgerModel.user_id)
            .order_by(score.desc(), ReputationLedgerModel.user_id.asc())
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            LeaderboardRow(user_id=row[0], score=int(row[1]), rank=int(row[2]))
            for row in rows
        ]
