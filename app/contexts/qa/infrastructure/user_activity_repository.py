"""用户活跃统计仓储（F06 徽章 / F13 D5 软删除剔除）：回答数/采纳数 + 四类行为活跃日。"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, func, select, union
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.contexts.qa.domain.comment import CommentTarget
from app.contexts.qa.domain.vote import VoteTarget
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
                )
                .select_from(AnswerModel)
                .join(QuestionModel, QuestionModel.id == AnswerModel.question_id)
                .where(
                    AnswerModel.author_id == user_id,
                    AnswerModel.deleted_at.is_(None),
                    QuestionModel.deleted_at.is_(None),
                )
            )
        ).one()
        return int(row[0]), int(row[1])

    async def active_dates(self, user_id: UUID) -> list[date]:
        days = union(
            # 1. 活跃问题
            select(_active_day(QuestionModel.created_at).label("day")).where(
                QuestionModel.author_id == user_id,
                QuestionModel.deleted_at.is_(None),
            ),
            # 2. 活跃回答（同时排除父问题已删）
            select(_active_day(AnswerModel.created_at).label("day"))
            .select_from(AnswerModel)
            .join(QuestionModel, QuestionModel.id == AnswerModel.question_id)
            .where(
                AnswerModel.author_id == user_id,
                AnswerModel.deleted_at.is_(None),
                QuestionModel.deleted_at.is_(None),
            ),
            # 3. 活跃问题下的题评
            select(_active_day(CommentModel.created_at).label("day"))
            .select_from(CommentModel)
            .join(QuestionModel, QuestionModel.id == CommentModel.target_id)
            .where(
                CommentModel.author_id == user_id,
                CommentModel.target_type == CommentTarget.QUESTION.value,
                QuestionModel.deleted_at.is_(None),
            ),
            # 4. 活跃回答下的答评（同时排除父问题已删）
            select(_active_day(CommentModel.created_at).label("day"))
            .select_from(CommentModel)
            .join(AnswerModel, AnswerModel.id == CommentModel.target_id)
            .join(QuestionModel, QuestionModel.id == AnswerModel.question_id)
            .where(
                CommentModel.author_id == user_id,
                CommentModel.target_type == CommentTarget.ANSWER.value,
                AnswerModel.deleted_at.is_(None),
                QuestionModel.deleted_at.is_(None),
            ),
            # 5. 活跃问题下的题票
            select(_active_day(VoteModel.created_at).label("day"))
            .select_from(VoteModel)
            .join(QuestionModel, QuestionModel.id == VoteModel.target_id)
            .where(
                VoteModel.user_id == user_id,
                VoteModel.target_type == VoteTarget.QUESTION.value,
                QuestionModel.deleted_at.is_(None),
            ),
            # 6. 活跃回答下的答票（同时排除父问题已删）
            select(_active_day(VoteModel.created_at).label("day"))
            .select_from(VoteModel)
            .join(AnswerModel, AnswerModel.id == VoteModel.target_id)
            .join(QuestionModel, QuestionModel.id == AnswerModel.question_id)
            .where(
                VoteModel.user_id == user_id,
                VoteModel.target_type == VoteTarget.ANSWER.value,
                AnswerModel.deleted_at.is_(None),
                QuestionModel.deleted_at.is_(None),
            ),
        ).subquery()
        rows = (
            await self._session.execute(select(days.c.day).order_by(days.c.day))
        ).scalars().all()
        return [row for row in rows]
