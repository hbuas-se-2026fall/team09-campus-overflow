from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, exists, select
from sqlalchemy import update as sql_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.qa.domain.answer import Answer
from app.contexts.qa.domain.errors import (
    AnswerAlreadyAcceptedError,
    AnswerNotFoundError,
    QuestionClosedError,
)
from app.contexts.qa.domain.question import QuestionStatus
from app.contexts.qa.domain.value_objects import Body
from app.contexts.qa.domain.vote import VoteTarget
from app.contexts.qa.infrastructure.models import AnswerModel, QuestionModel, VoteModel
from app.contexts.qa.infrastructure.sql_expressions import net_votes_expr


class SqlAlchemyAnswerRepository:
    """AnswerRepository 端口的 SQLAlchemy 实现。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, answer: Answer) -> None:
        self._session.add(
            AnswerModel(
                id=answer.id,
                body=answer.body.value,
                question_id=answer.question_id,
                author_id=answer.author_id,
                is_accepted=answer.is_accepted,
                created_at=answer.created_at,
            )
        )
        await self._session.flush()

    async def update(self, answer: Answer) -> None:
        # 采纳翻转（US-V03）：只同步可变态 is_accepted。
        # 并发兜底双保险：① 部分唯一索引 uq_answers_one_accepted_per_question 防"同题多答案"
        # （AC-12）；② 下方条件 UPDATE（WHERE is_accepted=false + rowcount）防"同一 answer 行
        # 重复翻转"——第五路 K-03：应用层先读后写在并发下可多路过检查；条件更新下 PG 行锁
        # 等待后按最新版本重判 WHERE，仅 1 路 rowcount=1，其余归 409。
        model = await self._session.get(AnswerModel, answer.id)
        if model is None:  # 理论不可达（用例先 get_by_id），防御性
            return
        stmt = (
            sql_update(AnswerModel)
            .where(AnswerModel.id == answer.id, AnswerModel.is_accepted.is_(False))
            .values(is_accepted=True)
            .execution_options(synchronize_session=False)
        )
        try:
            result = cast(CursorResult[Any], await self._session.execute(stmt))
        except IntegrityError as exc:
            # 同题【不同】答案并发抢采：部分唯一索引在首个事务提交后令后到者的索引
            # 插入失败（AC-12 库级兜底，289a001 条件 UPDATE 重写时曾遗漏本翻译致 400）。
            raise AnswerAlreadyAcceptedError("该问题已有采纳答案（并发兜底）") from exc
        if result.rowcount == 0:
            raise AnswerAlreadyAcceptedError("该答案已被采纳")

    async def update_body(self, answer: Answer) -> None:
        """F12：仅更新回答正文（条件 UPDATE 兜底所属问题未关闭，绝不触碰 is_accepted）。"""
        open_question_exists = exists(
            select(1)
            .where(
                QuestionModel.id == AnswerModel.question_id,
                QuestionModel.status != QuestionStatus.CLOSED.value,
            )
            .correlate(AnswerModel)
        )
        stmt = (
            sql_update(AnswerModel)
            .where(AnswerModel.id == answer.id, open_question_exists)
            .values(body=answer.body.value)
            .execution_options(synchronize_session=False)
        )
        result = cast(CursorResult[Any], await self._session.execute(stmt))
        if result.rowcount > 0:
            return

        row = (
            await self._session.execute(
                select(QuestionModel.status)
                .select_from(AnswerModel)
                .join(QuestionModel, QuestionModel.id == AnswerModel.question_id)
                .where(AnswerModel.id == answer.id)
            )
        ).first()
        if row is None:
            raise AnswerNotFoundError("回答不存在")
        raise QuestionClosedError("已关闭的问题不可编辑回答（并发兜底）")

    async def get_by_id(self, answer_id: UUID) -> Answer | None:
        model = (
            await self._session.execute(
                select(AnswerModel).where(AnswerModel.id == answer_id)
            )
        ).scalar_one_or_none()
        if model is None:
            return None
        return Answer(
            id=model.id,
            question_id=model.question_id,
            author_id=model.author_id,
            body=Body(model.body),
            created_at=model.created_at,
            is_accepted=model.is_accepted,
            votes_count=await self._net_votes(VoteTarget.ANSWER, model.id),
        )

    async def _net_votes(self, target_type: VoteTarget, target_id: UUID) -> int:
        stmt = (
            select(net_votes_expr())
            .select_from(VoteModel)
            .where(
                VoteModel.target_type == target_type.value,
                VoteModel.target_id == target_id,
            )
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def list_by_question(self, question_id: UUID) -> list[Answer]:
        # D2 排序（净票口径 v3 #1）：已采纳恒最前 > 净票数降序 > 时间正序 > id tiebreaker。
        # 每答净票用相关子查询聚合，避免 JOIN 折叠行数。
        net = (
            select(net_votes_expr())
            .where(
                VoteModel.target_type == VoteTarget.ANSWER.value,
                VoteModel.target_id == AnswerModel.id,
            )
            .correlate(AnswerModel)
            .scalar_subquery()
        )
        stmt = (
            select(AnswerModel, net.label("net_votes"))
            .where(AnswerModel.question_id == question_id)
            .order_by(
                AnswerModel.is_accepted.desc(),
                net.desc(),
                AnswerModel.created_at.asc(),
                AnswerModel.id.asc(),
            )
        )
        rows = (await self._session.execute(stmt)).all()
        return [
            Answer(
                id=model.id,
                question_id=model.question_id,
                author_id=model.author_id,
                body=Body(model.body),
                created_at=model.created_at,
                is_accepted=model.is_accepted,
                votes_count=int(net_votes),
            )
            for model, net_votes in rows
        ]
