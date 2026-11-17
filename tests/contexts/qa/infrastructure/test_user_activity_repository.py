"""用户活跃统计仓储集成测试（F06）：回答数/采纳数 + 四类行为活跃日。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.contexts.identity.application.commands import RegisterCommand
from app.contexts.identity.application.register_use_case import RegisterUseCase
from app.contexts.identity.infrastructure.password_hasher import BcryptPasswordHasher
from app.contexts.identity.infrastructure.repository import SqlAlchemyUserRepository
from app.contexts.qa.infrastructure.models import (
    AnswerModel,
    CommentModel,
    QuestionModel,
    VoteModel,
)
from app.contexts.qa.infrastructure.user_activity_repository import (
    SqlAlchemyUserActivityRepository,
)
from app.shared.engine import session_factory

pytestmark = pytest.mark.integration


async def _make_user() -> uuid.UUID:
    async with session_factory() as session:
        use_case = RegisterUseCase(SqlAlchemyUserRepository(session), BcryptPasswordHasher())
        user = await use_case.execute(
            RegisterCommand(
                role="student",
                email=f"{uuid.uuid4()}@stu.edu.cn",
                password="Passw0rd8",
                student_id=str(uuid.uuid4().int)[:10],
            )
        )
        await session.commit()
        return user.id


def _question(user_id: uuid.UUID, at: datetime) -> QuestionModel:
    return QuestionModel(
        id=uuid.uuid4(),
        title="活跃统计测试问题",
        body="F06 活跃日统计：验证四类内容行为按自然日聚合。",
        author_id=user_id,
        created_at=at,
        status="open",
    )


async def test_answer_stats_counts_total_and_accepted() -> None:
    user_id = await _make_user()
    async with session_factory() as session:
        question = _question(user_id, datetime(2024, 1, 1, 4, tzinfo=UTC))
        session.add(question)
        await session.flush()  # 先落问题，满足 answers.question_id 外键
        session.add(
            AnswerModel(
                id=uuid.uuid4(),
                body="采纳回答",
                question_id=question.id,
                author_id=user_id,
                is_accepted=True,
                created_at=datetime(2024, 1, 2, 4, tzinfo=UTC),
            )
        )
        session.add(
            AnswerModel(
                id=uuid.uuid4(),
                body="未采纳回答",
                question_id=question.id,
                author_id=user_id,
                is_accepted=False,
                created_at=datetime(2024, 1, 3, 4, tzinfo=UTC),
            )
        )
        await session.commit()

        stats = await SqlAlchemyUserActivityRepository(session).answer_stats(user_id)
        assert stats == (2, 1)


async def test_active_dates_unions_four_sources_in_shanghai_time() -> None:
    user_id = await _make_user()
    question_id = uuid.uuid4()
    async with session_factory() as session:
        # 04:00 UTC = 12:00 上海，四个自然日：1/1、1/2、1/4、1/5
        session.add(
            QuestionModel(
                id=question_id,
                title="四类活跃日来源",
                body="问题、回答、评论、投票各贡献一个活跃日。",
                author_id=user_id,
                created_at=datetime(2024, 1, 1, 4, tzinfo=UTC),
                status="open",
            )
        )
        await session.flush()  # 先落问题，满足 answers.question_id 外键
        session.add(
            AnswerModel(
                id=uuid.uuid4(),
                body="回答贡献 1/2",
                question_id=question_id,
                author_id=user_id,
                is_accepted=False,
                created_at=datetime(2024, 1, 2, 4, tzinfo=UTC),
            )
        )
        session.add(
            CommentModel(
                id=uuid.uuid4(),
                body="评论贡献 1/4",
                target_type="question",
                target_id=question_id,
                author_id=user_id,
                created_at=datetime(2024, 1, 4, 4, tzinfo=UTC),
            )
        )
        session.add(
            VoteModel(
                id=uuid.uuid4(),
                user_id=user_id,
                target_type="question",
                target_id=question_id,
                direction="up",
                created_at=datetime(2024, 1, 5, 4, tzinfo=UTC),
            )
        )
        await session.commit()

        days = await SqlAlchemyUserActivityRepository(session).active_dates(user_id)
        assert [d.isoformat() for d in days] == [
            "2024-01-01",
            "2024-01-02",
            "2024-01-04",
            "2024-01-05",
        ]


async def test_active_dates_uses_shanghai_calendar_day() -> None:
    """UTC 1/1 16:30 = 上海 1/2 00:30，活跃日应记 1/2。"""
    user_id = await _make_user()
    async with session_factory() as session:
        session.add(_question(user_id, datetime(2024, 1, 1, 16, 30, tzinfo=UTC)))
        await session.commit()

        days = await SqlAlchemyUserActivityRepository(session).active_dates(user_id)
        assert [d.isoformat() for d in days] == ["2024-01-02"]


async def test_no_activity_returns_zero_and_empty() -> None:
    user_id = await _make_user()
    async with session_factory() as session:
        repo = SqlAlchemyUserActivityRepository(session)
        assert await repo.answer_stats(user_id) == (0, 0)
        assert await repo.active_dates(user_id) == []
