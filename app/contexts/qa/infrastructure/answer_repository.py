from __future__ import annotations

from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, exists, select
from sqlalchemy import update as sql_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.qa.domain.answer import Answer
from app.contexts.qa.domain.errors import (
    AcceptedAnswerCannotDeleteError,
    AnswerAlreadyAcceptedError,
    AnswerNotFoundError,
    QuestionClosedError,
    QuestionNotFoundError,
)
from app.contexts.qa.domain.question import QuestionStatus
from app.contexts.qa.domain.value_objects import Body
from app.contexts.qa.domain.vote import VoteTarget
from app.contexts.qa.infrastructure.models import AnswerModel, QuestionModel, VoteModel
from app.contexts.qa.infrastructure.sql_expressions import net_votes_expr


def _to_domain(model: AnswerModel, *, votes_count: int = 0) -> Answer:
    return Answer(
        id=model.id,
        question_id=model.question_id,
        author_id=model.author_id,
        body=Body(model.body),
        created_at=model.created_at,
        is_accepted=model.is_accepted,
        votes_count=votes_count,
        deleted_at=model.deleted_at,
        is_teacher_verified=bool(model.is_teacher_verified),
        verified_by=model.verified_by,
        verified_at=model.verified_at,
    )


def _active_open_question_exists() -> Any:
    """F12/F15 共用子查询谓词：父问题未软删除且处于 open 态。"""
    return exists(
        select(1)
        .where(
            QuestionModel.id == AnswerModel.question_id,
            QuestionModel.deleted_at.is_(None),
            QuestionModel.status != QuestionStatus.CLOSED.value,
        )
        .correlate(AnswerModel)
    )


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
                is_teacher_verified=answer.is_teacher_verified,
                verified_by=answer.verified_by,
                verified_at=answer.verified_at,
            )
        )
        await self._session.flush()

    async def update(self, answer: Answer) -> None:
        # 采纳翻转（US-V03）：只同步可变态 is_accepted，并发与软删除双兜底：
        # ① 部分唯一索引 uq_answers_one_accepted_per_question 防同题多采纳；
        # ② 条件 UPDATE 守住回答未删、未采纳且父问题未删未关，rowcount=0 精准转译 404/409。
        stmt = (
            sql_update(AnswerModel)
            .where(
                AnswerModel.id == answer.id,
                AnswerModel.is_accepted.is_(False),
                AnswerModel.deleted_at.is_(None),
                _active_open_question_exists(),
            )
            .values(is_accepted=True)
            .execution_options(synchronize_session=False)
        )
        try:
            result = cast(CursorResult[Any], await self._session.execute(stmt))
        except IntegrityError as exc:
            raise AnswerAlreadyAcceptedError("该问题已有采纳答案（并发兜底）") from exc
        if result.rowcount > 0:
            return
        row = (
            await self._session.execute(
                select(
                    AnswerModel.is_accepted,
                    AnswerModel.deleted_at,
                    QuestionModel.deleted_at,
                    QuestionModel.status,
                )
                .select_from(AnswerModel)
                .join(QuestionModel, QuestionModel.id == AnswerModel.question_id)
                .where(AnswerModel.id == answer.id)
            )
        ).first()
        if row is None or row[1] is not None:
            raise AnswerNotFoundError("回答不存在")
        if row[2] is not None:
            raise QuestionNotFoundError("问题不存在")
        if row[0]:
            raise AnswerAlreadyAcceptedError("该答案已被采纳")
        raise QuestionClosedError("已关闭的问题不可采纳（并发兜底）")

    async def _raise_missing_or_closed(
        self, answer_id: UUID, *, closed_message: str
    ) -> None:
        row = (
            await self._session.execute(
                select(
                    AnswerModel.deleted_at,
                    QuestionModel.deleted_at,
                    QuestionModel.status,
                )
                .select_from(AnswerModel)
                .join(QuestionModel, QuestionModel.id == AnswerModel.question_id)
                .where(AnswerModel.id == answer_id)
            )
        ).first()
        if row is None or row[0] is not None:
            raise AnswerNotFoundError("回答不存在")
        if row[1] is not None:
            raise QuestionNotFoundError("问题不存在")
        raise QuestionClosedError(closed_message)

    async def update_body(self, answer: Answer) -> None:
        """F12/F13：仅更新回答正文（条件 UPDATE 兜底回答未删且所属问题未删未关）。"""
        stmt = (
            sql_update(AnswerModel)
            .where(
                AnswerModel.id == answer.id,
                AnswerModel.deleted_at.is_(None),
                _active_open_question_exists(),
            )
            .values(body=answer.body.value)
            .execution_options(synchronize_session=False)
        )
        result = cast(CursorResult[Any], await self._session.execute(stmt))
        if result.rowcount > 0:
            return
        await self._raise_missing_or_closed(
            answer.id,
            closed_message="已关闭的问题不可编辑回答（并发兜底）",
        )

    async def update_verification(self, answer: Answer) -> None:
        """F15：仅更新回答认证状态（条件 UPDATE 兜底回答未删且所属问题未删未关）。"""
        stmt = (
            sql_update(AnswerModel)
            .where(
                AnswerModel.id == answer.id,
                AnswerModel.deleted_at.is_(None),
                _active_open_question_exists(),
            )
            .values(
                is_teacher_verified=answer.is_teacher_verified,
                verified_by=answer.verified_by,
                verified_at=answer.verified_at,
            )
            .execution_options(synchronize_session=False)
        )
        result = cast(CursorResult[Any], await self._session.execute(stmt))
        if result.rowcount > 0:
            return
        await self._raise_missing_or_closed(
            answer.id,
            closed_message="已关闭的问题不可变更回答认证状态（并发兜底）",
        )

    async def soft_delete(self, answer_id: UUID, deleted_at: datetime) -> bool:
        """F13 条件软删除：父问题未删、回答未删且未采纳时写入 deleted_at。"""
        active_question_exists = exists(
            select(1)
            .where(
                QuestionModel.id == AnswerModel.question_id,
                QuestionModel.deleted_at.is_(None),
            )
            .correlate(AnswerModel)
        )
        stmt = (
            sql_update(AnswerModel)
            .where(
                AnswerModel.id == answer_id,
                AnswerModel.deleted_at.is_(None),
                AnswerModel.is_accepted.is_(False),
                active_question_exists,
            )
            .values(deleted_at=deleted_at)
            .execution_options(synchronize_session=False)
        )
        result = cast(CursorResult[Any], await self._session.execute(stmt))
        if result.rowcount > 0:
            return True

        row = (
            await self._session.execute(
                select(
                    AnswerModel.deleted_at,
                    AnswerModel.is_accepted,
                    QuestionModel.deleted_at,
                )
                .select_from(AnswerModel)
                .join(QuestionModel, QuestionModel.id == AnswerModel.question_id)
                .where(AnswerModel.id == answer_id)
            )
        ).first()
        if row is None:
            raise AnswerNotFoundError("回答不存在")
        if row[2] is not None:
            raise QuestionNotFoundError("问题不存在")
        if row[0] is not None:
            return False
        if row[1]:
            raise AcceptedAnswerCannotDeleteError("已采纳的回答不可删除（并发兜底）")
        return False

    async def get_by_id(
        self, answer_id: UUID, *, include_deleted: bool = False
    ) -> Answer | None:
        # update() / update_body() / soft_delete() 使用 synchronize_session=False，
        # populate_existing=True 避免同一会话内回读到 identity map 旧缓存。
        stmt = select(AnswerModel).where(AnswerModel.id == answer_id)
        if not include_deleted:
            stmt = stmt.join(
                QuestionModel, QuestionModel.id == AnswerModel.question_id
            ).where(
                AnswerModel.deleted_at.is_(None),
                QuestionModel.deleted_at.is_(None),
            )
        stmt = stmt.execution_options(populate_existing=True)
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return None
        return _to_domain(
            model, votes_count=await self._net_votes(VoteTarget.ANSWER, model.id)
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
        # 每答净票用相关子查询聚合，避免 JOIN 折叠行数；同时排除自身或父问题已删行（F13 D4）。
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
            .join(QuestionModel, QuestionModel.id == AnswerModel.question_id)
            .where(
                AnswerModel.question_id == question_id,
                AnswerModel.deleted_at.is_(None),
                QuestionModel.deleted_at.is_(None),
            )
            .order_by(
                AnswerModel.is_accepted.desc(),
                net.desc(),
                AnswerModel.created_at.asc(),
                AnswerModel.id.asc(),
            )
        )
        rows = (await self._session.execute(stmt)).all()
        return [_to_domain(model, votes_count=int(net_votes)) for model, net_votes in rows]
