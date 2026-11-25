"""课程贡献排行榜 SQLAlchemy 只读仓储（F17，零跨上下文写或声誉耦合）。"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.qa.domain.repository import CourseLeaderboardEntry
from app.contexts.qa.domain.vote import VoteTarget
from app.contexts.qa.infrastructure.models import (
    AnswerModel,
    QuestionModel,
    VoteModel,
)
from app.contexts.qa.infrastructure.sql_expressions import net_votes_expr


class SqlAlchemyCourseLeaderboardRepository:
    """CourseLeaderboardRepository 的 SQLAlchemy 只读聚合实现。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_top_contributors(
        self, course_id: UUID, *, limit: int
    ) -> list[CourseLeaderboardEntry]:
        # 先按回答粒度计算单条净票，避免直接 JOIN votes 放大 answer_count/accepted_count
        answer_net_votes = (
            select(net_votes_expr())
            .where(
                VoteModel.target_type == VoteTarget.ANSWER.value,
                VoteModel.target_id == AnswerModel.id,
            )
            .correlate(AnswerModel)
            .scalar_subquery()
        )
        per_answer = (
            select(
                AnswerModel.author_id.label("author_id"),
                case((AnswerModel.is_accepted.is_(True), 1), else_=0).label(
                    "is_accepted_int"
                ),
                answer_net_votes.label("answer_votes"),
            )
            .join(QuestionModel, QuestionModel.id == AnswerModel.question_id)
            .where(
                QuestionModel.course_id == course_id,
                QuestionModel.deleted_at.is_(None),
                AnswerModel.deleted_at.is_(None),
            )
        ).subquery()

        accepted_sum = func.coalesce(func.sum(per_answer.c.is_accepted_int), 0)
        net_votes_sum = func.coalesce(func.sum(per_answer.c.answer_votes), 0)
        answer_cnt = func.count()
        rank_expr = func.rank().over(
            order_by=(accepted_sum.desc(), net_votes_sum.desc())
        )

        stmt = (
            select(
                per_answer.c.author_id,
                accepted_sum.label("accepted_count"),
                net_votes_sum.label("net_votes"),
                answer_cnt.label("answer_count"),
                rank_expr.label("rank"),
            )
            .group_by(per_answer.c.author_id)
            .order_by(
                accepted_sum.desc(),
                net_votes_sum.desc(),
                answer_cnt.desc(),
                per_answer.c.author_id.asc(),
            )
            .limit(limit)
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            CourseLeaderboardEntry(
                user_id=row[0],
                accepted_count=int(row[1]),
                net_votes=int(row[2]),
                answer_count=int(row[3]),
                rank=int(row[4]),
            )
            for row in rows
        ]
