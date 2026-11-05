from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.qa.domain.errors import AlreadyVotedError
from app.contexts.qa.domain.vote import Vote, VoteDirection, VoteTarget
from app.contexts.qa.infrastructure.models import VoteModel


class SqlAlchemyVoteRepository:
    """VoteRepository 端口的 SQLAlchemy 实现。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_user_target(
        self, user_id: UUID, target_type: VoteTarget, target_id: UUID
    ) -> Vote | None:
        model = (
            await self._session.execute(
                select(VoteModel).where(
                    VoteModel.user_id == user_id,
                    VoteModel.target_type == target_type.value,
                    VoteModel.target_id == target_id,
                )
            )
        ).scalar_one_or_none()
        if model is None:
            return None
        return self._to_domain(model)

    async def add(self, vote: Vote) -> None:
        self._session.add(
            VoteModel(
                id=vote.id,
                user_id=vote.user_id,
                target_type=vote.target_type.value,
                target_id=vote.target_id,
                direction=vote.direction.value,
                created_at=vote.created_at,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # 并发窗口内重复票：复合唯一索引兜底 → 重复票语义（与 identity 注册并发兜底同模式）。
            # 不回显 exc.orig（含约束名/DB 细节，Bug-5 泄露）——详情随异常链入服务端日志
            raise AlreadyVotedError("已对该对象投过票（并发兜底）") from exc

    @staticmethod
    def _to_domain(model: VoteModel) -> Vote:
        return Vote(
            id=model.id,
            user_id=model.user_id,
            target_type=VoteTarget(model.target_type),
            target_id=model.target_id,
            direction=VoteDirection(model.direction),
            created_at=model.created_at,
        )
