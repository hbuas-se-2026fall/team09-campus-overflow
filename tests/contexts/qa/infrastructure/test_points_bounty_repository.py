"""积分/悬赏仓储集成测试（F07）：开户幂等、条件扣减、唯一 open 悬赏、结算/退款一次。"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from app.contexts.identity.application.commands import RegisterCommand
from app.contexts.identity.application.register_use_case import RegisterUseCase
from app.contexts.identity.infrastructure.password_hasher import BcryptPasswordHasher
from app.contexts.identity.infrastructure.repository import SqlAlchemyUserRepository
from app.contexts.qa.application.bounty_service import BountyService
from app.contexts.qa.domain.bounty import Bounty, BountyStatus
from app.contexts.qa.domain.errors import BountyAlreadyActiveError
from app.contexts.qa.infrastructure.bounty_repository import SqlAlchemyBountyRepository
from app.contexts.qa.infrastructure.models import PointLedgerModel, QuestionModel
from app.contexts.qa.infrastructure.points_repository import SqlAlchemyPointsRepository
from app.shared.engine import session_factory

pytestmark = pytest.mark.integration


async def _make_user() -> uuid.UUID:
    async with session_factory() as session:
        use_case = RegisterUseCase(SqlAlchemyUserRepository(session), BcryptPasswordHasher())
        user = await use_case.execute(
            RegisterCommand(
                role="teacher",
                email=f"{uuid.uuid4()}@edu.cn",
                password="Passw0rd8",
                staff_id=f"T{uuid.uuid4().int % 100_000_000:08d}",
            )
        )
        await session.commit()
        return user.id


async def test_teacher_account_grants_once_and_deducts_conditionally() -> None:
    user_id = await _make_user()
    async with session_factory() as session:
        repo = SqlAlchemyPointsRepository(session)
        assert await repo.ensure_teacher_account(user_id) == 100
        assert await repo.ensure_teacher_account(user_id) == 100  # 幂等
        await session.commit()
        grant_rows = (
            await session.execute(
                select(func.count())
                .select_from(PointLedgerModel)
                .where(
                    PointLedgerModel.user_id == user_id,
                    PointLedgerModel.source == "grant",
                )
            )
        ).scalar_one()
        assert grant_rows == 1

        assert await repo.deduct(user_id, 30) is True
        assert await repo.deduct(user_id, 80) is False
        assert await repo.balance(user_id) == 70


async def test_credit_opens_zero_account_without_grant() -> None:
    user_id = await _make_user()
    async with session_factory() as session:
        repo = SqlAlchemyPointsRepository(session)
        await repo.credit(user_id, 15)
        await session.commit()
        assert await repo.balance(user_id) == 15


async def _bounty(question_id: uuid.UUID, teacher_id: uuid.UUID, amount: int) -> Bounty:
    return Bounty(
        id=uuid.uuid4(),
        question_id=question_id,
        teacher_id=teacher_id,
        amount=amount,
        status=BountyStatus.OPEN,
        created_at=datetime.now(UTC),
        settled_at=None,
    )


async def test_only_one_open_bounty_per_question_and_transitions_once() -> None:
    teacher_id = await _make_user()
    question_id = uuid.uuid4()
    async with session_factory() as session:
        # 先建真实问题满足 question_bounties.question_id 外键
        session.add(
            QuestionModel(
                id=question_id,
                title="悬赏仓储测试问题",
                body="F07 悬赏仓储：唯一 open 与条件状态迁移。",
                author_id=teacher_id,
                created_at=datetime.now(UTC),
                status="open",
            )
        )
        await session.commit()

        repo = SqlAlchemyBountyRepository(session)
        bounty = await _bounty(question_id, teacher_id, 10)
        await repo.add(bounty)
        await session.commit()

        with pytest.raises(BountyAlreadyActiveError):
            await repo.add(await _bounty(question_id, teacher_id, 5))
        # 唯一键冲突让当前事务进入失败态；生产路径由请求级 rollback 丢弃
        # 本次扣减+插入（余额自动恢复），测试在此显式回滚后继续验证状态迁移。
        await session.rollback()

        settled = await repo.settle(question_id)
        assert settled is not None
        assert settled.status is BountyStatus.SETTLED
        assert await repo.settle(question_id) is None
        assert await repo.refund(question_id) is None

        await session.commit()

        # 结算后可再发新悬赏
        await repo.add(await _bounty(question_id, teacher_id, 20))
        await session.commit()
        active = await repo.get_active(question_id)
        assert active is not None
        assert active.amount == 20


async def _seed_bounty(
    teacher_id: uuid.UUID, amount: int
) -> tuple[uuid.UUID, Bounty]:
    question_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            QuestionModel(
                id=question_id,
                title="悬赏并发测试问题",
                body="F07 并发：采纳结算与关闭退款各只发生一次。",
                author_id=teacher_id,
                created_at=datetime.now(UTC),
                status="open",
            )
        )
        await session.commit()
    async with session_factory() as session:
        service = BountyService(
            SqlAlchemyBountyRepository(session), SqlAlchemyPointsRepository(session)
        )
        bounty = await service.create(question_id, teacher_id, amount)
        await session.commit()
        return question_id, bounty


async def _settle_once(question_id: uuid.UUID, author_id: uuid.UUID) -> bool:
    async with session_factory() as session:
        service = BountyService(
            SqlAlchemyBountyRepository(session), SqlAlchemyPointsRepository(session)
        )
        settled = await service.settle_on_accept(question_id, author_id)
        await session.commit()
        return settled


async def _refund_once(question_id: uuid.UUID) -> bool:
    async with session_factory() as session:
        service = BountyService(
            SqlAlchemyBountyRepository(session), SqlAlchemyPointsRepository(session)
        )
        refunded = await service.refund_on_close(question_id)
        await session.commit()
        return refunded


async def test_concurrent_settlement_credits_once() -> None:
    """两路并发结算：恰一路成功、答主只入账一次、流水恰一行。"""
    teacher_id = await _make_user()
    author_id = await _make_user()
    question_id, bounty = await _seed_bounty(teacher_id, 30)

    results = await asyncio.gather(
        _settle_once(question_id, author_id),
        _settle_once(question_id, author_id),
    )
    assert sorted(results) == [False, True]

    async with session_factory() as session:
        assert await SqlAlchemyPointsRepository(session).balance(author_id) == 30
        rows = (
            await session.execute(
                select(func.count())
                .select_from(PointLedgerModel)
                .where(
                    PointLedgerModel.source == "bounty_award",
                    PointLedgerModel.event_id == bounty.id,
                )
            )
        ).scalar_one()
        assert rows == 1


async def test_concurrent_refund_returns_once() -> None:
    """两路并发退款：恰一路成功、教师余额恢复一次、流水恰一行。"""
    teacher_id = await _make_user()
    question_id, bounty = await _seed_bounty(teacher_id, 20)

    results = await asyncio.gather(_refund_once(question_id), _refund_once(question_id))
    assert sorted(results) == [False, True]

    async with session_factory() as session:
        assert await SqlAlchemyPointsRepository(session).balance(teacher_id) == 100
        rows = (
            await session.execute(
                select(func.count())
                .select_from(PointLedgerModel)
                .where(
                    PointLedgerModel.source == "bounty_refund",
                    PointLedgerModel.event_id == bounty.id,
                )
            )
        ).scalar_one()
        assert rows == 1
