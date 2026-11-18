"""SqlAlchemyAnswerRepository.update_body 仓储集成测试（F12）。"""

from __future__ import annotations

import uuid

import pytest

from app.contexts.identity.application.commands import RegisterCommand
from app.contexts.identity.application.register_use_case import RegisterUseCase
from app.contexts.identity.infrastructure.password_hasher import BcryptPasswordHasher
from app.contexts.identity.infrastructure.repository import SqlAlchemyUserRepository
from app.contexts.qa.domain.answer import Answer
from app.contexts.qa.domain.errors import AnswerNotFoundError, QuestionClosedError
from app.contexts.qa.domain.question import Question
from app.contexts.qa.infrastructure.answer_repository import SqlAlchemyAnswerRepository
from app.contexts.qa.infrastructure.question_repository import SqlAlchemyQuestionRepository
from app.shared.engine import session_factory

pytestmark = pytest.mark.integration


async def _create_user() -> uuid.UUID:
    async with session_factory() as session:
        user = await RegisterUseCase(
            SqlAlchemyUserRepository(session), BcryptPasswordHasher()
        ).execute(
            RegisterCommand(
                role="student",
                email=f"{uuid.uuid4()}@stu.edu.cn",
                password="Passw0rd8",
                student_id=str(uuid.uuid4().int)[:10],
            )
        )
        await session.commit()
        return user.id


async def test_update_body_updates_text_without_touching_is_accepted() -> None:
    asker_id = await _create_user()
    author_id = await _create_user()

    async with session_factory() as session:
        q = Question.ask(title_value="问题", body_value="正文", author_id=asker_id)
        await SqlAlchemyQuestionRepository(session).add(q)
        a = Answer.post(question_id=q.id, author_id=author_id, body_value="原始回答")
        await SqlAlchemyAnswerRepository(session).add(a)
        await session.commit()

    async with session_factory() as session:
        repo = SqlAlchemyAnswerRepository(session)
        loaded = await repo.get_by_id(a.id)
        assert loaded is not None
        loaded.edit_body(body_value="更新后的正文")
        await repo.update_body(loaded)
        await session.commit()

    async with session_factory() as session:
        after = await SqlAlchemyAnswerRepository(session).get_by_id(a.id)
        assert after is not None
        assert after.body.value == "更新后的正文"
        assert after.is_accepted is False


async def test_update_body_db_guard_rejects_closed_question_and_missing_answer() -> None:
    asker_id = await _create_user()
    author_id = await _create_user()

    async with session_factory() as session:
        q = Question.ask(title_value="问题", body_value="正文", author_id=asker_id)
        await SqlAlchemyQuestionRepository(session).add(q)
        a = Answer.post(question_id=q.id, author_id=author_id, body_value="原始回答")
        await SqlAlchemyAnswerRepository(session).add(a)
        q.close()
        await SqlAlchemyQuestionRepository(session).update(q)
        await session.commit()

    async with session_factory() as session:
        a.edit_body(body_value="关闭后强写")
        with pytest.raises(QuestionClosedError):
            await SqlAlchemyAnswerRepository(session).update_body(a)

    async with session_factory() as session:
        missing = Answer.post(question_id=q.id, author_id=author_id, body_value="不存在")
        with pytest.raises(AnswerNotFoundError):
            await SqlAlchemyAnswerRepository(session).update_body(missing)
