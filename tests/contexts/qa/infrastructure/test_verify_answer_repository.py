"""SqlAlchemyAnswerRepository.update_verification 仓储集成测试（F15，真实 PG）。"""

from __future__ import annotations

import uuid

import pytest

from app.contexts.identity.application.commands import RegisterCommand
from app.contexts.identity.application.register_use_case import RegisterUseCase
from app.contexts.identity.infrastructure.password_hasher import BcryptPasswordHasher
from app.contexts.identity.infrastructure.repository import SqlAlchemyUserRepository
from app.contexts.qa.domain.answer import Answer
from app.contexts.qa.domain.errors import (
    AnswerNotFoundError,
    QuestionClosedError,
)
from app.contexts.qa.domain.question import Question
from app.contexts.qa.infrastructure.answer_repository import SqlAlchemyAnswerRepository
from app.contexts.qa.infrastructure.question_repository import (
    SqlAlchemyQuestionRepository,
)
from app.shared.engine import session_factory

pytestmark = pytest.mark.integration


async def _create_user(*, role: str = "student") -> uuid.UUID:
    async with session_factory() as session:
        if role == "teacher":
            cmd = RegisterCommand(
                role="teacher",
                email=f"f15-qarepo-{uuid.uuid4().hex[:10]}@edu.cn",
                password="Passw0rd8",
                staff_id=f"T{uuid.uuid4().int % 90_000_000 + 10_000_000}",
            )
        else:
            cmd = RegisterCommand(
                role="student",
                email=f"f15-qarepo-{uuid.uuid4().hex[:10]}@stu.edu.cn",
                password="Passw0rd8",
                student_id=str(uuid.uuid4().int)[:10],
            )
        user = await RegisterUseCase(
            SqlAlchemyUserRepository(session), BcryptPasswordHasher()
        ).execute(cmd)
        await session.commit()
        return user.id


async def test_update_verification_persists_restores_and_preserves_across_edits() -> None:
    asker_id = await _create_user()
    author_id = await _create_user()
    teacher_id = await _create_user(role="teacher")

    async with session_factory() as session:
        q = Question.ask(
            title_value="两阶段锁定（2PL）如何保证事务可串行化？",
            body_value="增长阶段与收缩阶段各自遵守什么加锁/解锁约束？",
            author_id=asker_id,
        )
        await SqlAlchemyQuestionRepository(session).add(q)
        a = Answer.post(
            question_id=q.id,
            author_id=author_id,
            body_value="严格两阶段锁定要求在事务提交前不释放任何排他锁，防止脏读与级联回滚。",
        )
        await SqlAlchemyAnswerRepository(session).add(a)
        await session.commit()

    async with session_factory() as session:
        repo = SqlAlchemyAnswerRepository(session)
        loaded = await repo.get_by_id(a.id)
        assert loaded is not None
        assert loaded.verify(teacher_id) is True
        await repo.update_verification(loaded)
        await session.commit()

    # get_by_id 与 list_by_question 均完整还原三个认证字段
    async with session_factory() as session:
        repo = SqlAlchemyAnswerRepository(session)
        fetched = await repo.get_by_id(a.id)
        listed = await repo.list_by_question(q.id)
        assert fetched is not None
        assert fetched.is_teacher_verified is True
        assert fetched.verified_by == teacher_id
        assert fetched.verified_at is not None
        assert len(listed) == 1
        assert listed[0].is_teacher_verified is True
        assert listed[0].verified_by == teacher_id
        assert listed[0].verified_at == fetched.verified_at

        # edit_body 与 accept 不破坏既有认证字段
        fetched.edit_body(
            body_value="严格两阶段锁定保证冲突可串行化，并消除级联回滚风险。"
        )
        await repo.update_body(fetched)
        fetched.accept()
        await repo.update(fetched)
        await session.commit()

    async with session_factory() as session:
        repo = SqlAlchemyAnswerRepository(session)
        after = await repo.get_by_id(a.id)
        assert after is not None
        assert after.is_teacher_verified is True
        assert after.verified_by == teacher_id
        assert after.unverify() is True
        await repo.update_verification(after)
        await session.commit()

    async with session_factory() as session:
        cleared = await SqlAlchemyAnswerRepository(session).get_by_id(a.id)
        assert cleared is not None
        assert cleared.is_teacher_verified is False
        assert cleared.verified_by is None
        assert cleared.verified_at is None


async def test_update_verification_db_guard_rejects_closed_and_missing() -> None:
    asker_id = await _create_user()
    author_id = await _create_user()
    teacher_id = await _create_user(role="teacher")

    async with session_factory() as session:
        q = Question.ask(
            title_value="操作系统中页框回收 Clock 算法如何近似 LRU？",
            body_value="访问位（reference bit）在二次扫描时何时清零？",
            author_id=asker_id,
        )
        await SqlAlchemyQuestionRepository(session).add(q)
        a = Answer.post(
            question_id=q.id,
            author_id=author_id,
            body_value="指针遇到访问位为 1 的页框将其清 0 后继续前进，首次遇到 0 即替换该页。",
        )
        await SqlAlchemyAnswerRepository(session).add(a)
        q.close()
        await SqlAlchemyQuestionRepository(session).update(q)
        await session.commit()

    async with session_factory() as session:
        a.verify(teacher_id)
        with pytest.raises(QuestionClosedError):
            await SqlAlchemyAnswerRepository(session).update_verification(a)

    async with session_factory() as session:
        missing = Answer.post(
            question_id=q.id, author_id=author_id, body_value="不存在回答"
        )
        missing.verify(teacher_id)
        with pytest.raises(AnswerNotFoundError):
            await SqlAlchemyAnswerRepository(session).update_verification(missing)
