"""用户活跃统计仓储（F06 徽章）：回答数/采纳数 + 四类行为活跃日。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, func, select, union
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.contexts.qa.infrastructure.models import (
    AnswerModel,
    CommentModel,
    QuestionModel,
    VoteModel,
)


def _active_day(column: InstrumentedAttribute[datetime]) -> ColumnElement[Any]:
    """timestamptz → Asia/Shanghai 自然日（PG date()）。"""
    return func.date(func.timezone("Asia/Shanghai", column))


class SqlAlchemyUserActivityRepository:
    """UserActivityRepository 端口实现（只读，无迁移）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def answer_stats(self, user_id: UUID) -> tuple[int, int]:
        row = (
            await self._session.execute(
                select(
                    func.count(),
                    func.count().filter(AnswerModel.is_accepted.is_(True)),
                ).where(AnswerModel.author_id == user_id)
            )
        ).one()
        return int(row[0]), int(row[1])

    async def active_dates(self, user_id: UUID) -> list[date]:
        days = union(
            select(_active_day(QuestionModel.created_at).label("day")).where(
                QuestionModel.author_id == user_id
            ),
            select(_active_day(AnswerModel.created_at).label("day")).where(
                AnswerModel.author_id == user_id
            ),
            select(_active_day(CommentModel.created_at).label("day")).where(
                CommentModel.author_id == user_id
            ),
            select(_active_day(VoteModel.created_at).label("day")).where(
                VoteModel.user_id == user_id
            ),
        ).subquery()
        rows = (
            await self._session.execute(select(days.c.day).order_by(days.c.day))
        ).scalars().all()
        return [row for row in rows]
