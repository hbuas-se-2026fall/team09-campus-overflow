"""悬赏仓储实现（F07/D13）：部分唯一索引防同题多 open；条件 UPDATE 保证结算/退款一次。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy import update as sql_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.qa.domain.bounty import Bounty, BountyStatus
from app.contexts.qa.domain.errors import BountyAlreadyActiveError
from app.contexts.qa.infrastructure.models import QuestionBountyModel


def _to_domain(model: QuestionBountyModel) -> Bounty:
    return Bounty(
        id=model.id,
        question_id=model.question_id,
        teacher_id=model.teacher_id,
        amount=model.amount,
        status=BountyStatus(model.status),
        created_at=model.created_at,
        settled_at=model.settled_at,
    )


class SqlAlchemyBountyRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, bounty: Bounty) -> None:
        self._session.add(
            QuestionBountyModel(
                id=bounty.id,
                question_id=bounty.question_id,
                teacher_id=bounty.teacher_id,
                amount=bounty.amount,
                status=bounty.status.value,
                created_at=bounty.created_at,
                settled_at=bounty.settled_at,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise BountyAlreadyActiveError("该问题已有进行中的悬赏") from exc

    async def get_active(self, question_id: UUID) -> Bounty | None:
        model = (
            await self._session.execute(
                select(QuestionBountyModel).where(
                    QuestionBountyModel.question_id == question_id,
                    QuestionBountyModel.status == BountyStatus.OPEN.value,
                )
            )
        ).scalar_one_or_none()
        return _to_domain(model) if model is not None else None

    async def _transition(
        self, question_id: UUID, status: BountyStatus
    ) -> Bounty | None:
        stmt = (
            sql_update(QuestionBountyModel)
            .where(
                QuestionBountyModel.question_id == question_id,
                QuestionBountyModel.status == BountyStatus.OPEN.value,
            )
            .values(status=status.value, settled_at=datetime.now(UTC))
            .returning(QuestionBountyModel)
            .execution_options(synchronize_session=False)
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_domain(model) if model is not None else None

    async def settle(self, question_id: UUID) -> Bounty | None:
        return await self._transition(question_id, BountyStatus.SETTLED)

    async def refund(self, question_id: UUID) -> Bounty | None:
        return await self._transition(question_id, BountyStatus.REFUNDED)
