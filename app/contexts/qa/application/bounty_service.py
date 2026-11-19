"""悬赏服务（F07）：创建冻结 / 采纳结算 / 关闭退款，全部同事务。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.contexts.qa.domain.bounty import Bounty, BountyStatus, PointsEntry
from app.contexts.qa.domain.errors import InsufficientPointsError
from app.contexts.qa.domain.repository import BountyRepository, PointsRepository


class BountyService:
    def __init__(
        self, bounty_repository: BountyRepository, points_repository: PointsRepository
    ) -> None:
        self._bounties = bounty_repository
        self._points = points_repository

    async def create(self, question_id: UUID, teacher_id: UUID, amount: int) -> Bounty:
        balance = await self._points.ensure_teacher_account(teacher_id)
        if balance < amount:
            raise InsufficientPointsError("积分不足，无法发起悬赏")
        if not await self._points.deduct(teacher_id, amount):
            raise InsufficientPointsError("积分不足，无法发起悬赏")
        now = datetime.now(UTC)
        bounty = Bounty(
            id=uuid4(),
            question_id=question_id,
            teacher_id=teacher_id,
            amount=amount,
            status=BountyStatus.OPEN,
            created_at=now,
            settled_at=None,
        )
        # 唯一索引冲突抛 BountyAlreadyActiveError；同事务扣减随回滚恢复
        await self._bounties.add(bounty)
        await self._points.append(
            teacher_id,
            PointsEntry(
                source="bounty",
                event_id=bounty.id,
                delta=-amount,
                reason="发起悬赏冻结",
                occurred_at=now,
            ),
        )
        return bounty

    async def settle_on_accept(self, question_id: UUID, answer_author_id: UUID) -> bool:
        """采纳时结算；条件更新保证并发下只成功一次。"""
        bounty = await self._bounties.settle(question_id)
        if bounty is None:
            return False
        now = datetime.now(UTC)
        await self._points.credit(answer_author_id, bounty.amount)
        await self._points.append(
            answer_author_id,
            PointsEntry(
                source="bounty_award",
                event_id=bounty.id,
                delta=bounty.amount,
                reason="悬赏结算",
                occurred_at=now,
            ),
        )
        return True

    async def _refund(self, question_id: UUID, *, reason: str) -> bool:
        """未采纳开放悬赏全额退款共用实现；条件更新保证并发下只退一次。"""
        bounty = await self._bounties.refund(question_id)
        if bounty is None:
            return False
        now = datetime.now(UTC)
        await self._points.credit(bounty.teacher_id, bounty.amount)
        await self._points.append(
            bounty.teacher_id,
            PointsEntry(
                source="bounty_refund",
                event_id=bounty.id,
                delta=bounty.amount,
                reason=reason,
                occurred_at=now,
            ),
        )
        return True

    async def refund_on_close(self, question_id: UUID) -> bool:
        """关闭且未采纳时全额退款；条件更新保证只退一次。"""
        return await self._refund(question_id, reason="悬赏退款")

    async def refund_on_delete(self, question_id: UUID) -> bool:
        """软删除且存在开放悬赏时全额退款；条件更新保证只退一次（F13 D3）。"""
        return await self._refund(question_id, reason="悬赏退款")
