"""EditAnswerUseCase 单元测试（fake 仓储，不连库，进 CI）。"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.contexts.qa.application.commands import EditAnswerCommand
from app.contexts.qa.application.edit_answer_use_case import EditAnswerUseCase
from app.contexts.qa.domain.answer import Answer
from app.contexts.qa.domain.errors import (
    AnswerNotFoundError,
    NotAnswerAuthorError,
    QuestionClosedError,
    QuestionNotFoundError,
)
from app.contexts.qa.domain.question import Question
from app.contexts.qa.domain.repository import QuestionFilter, QuestionSort
from app.shared.errors import DomainValidationError


class _FakeQuestionRepo:
    def __init__(self, questions: list[Question]) -> None:
        self._items = {q.id: q for q in questions}
        self.for_update_calls: list[tuple[UUID, bool]] = []

    async def add(self, question: Question) -> None:
        self._items[question.id] = question

    async def update(self, question: Question) -> None:
        self._items[question.id] = question

    async def get_by_id(
        self, question_id: UUID, *, for_update: bool = False
    ) -> Question | None:
        self.for_update_calls.append((question_id, for_update))
        return self._items.get(question_id)

    async def list_related(self, question_id: UUID, limit: int) -> list[Question]:
        return []

    async def list_paginated(
        self,
        page: int,
        page_size: int,
        sort: QuestionSort = QuestionSort.LATEST,
        filters: QuestionFilter | None = None,
    ) -> tuple[list[Question], int]:
        items = list(self._items.values())
        return items, len(items)


class _FakeAnswerRepo:
    def __init__(self, answers: list[Answer]) -> None:
        self._items = {a.id: a for a in answers}
        self.body_updated: list[Answer] = []
        self.accept_updated: list[Answer] = []

    async def add(self, answer: Answer) -> None:
        self._items[answer.id] = answer

    async def update(self, answer: Answer) -> None:
        self.accept_updated.append(answer)

    async def update_body(self, answer: Answer) -> None:
        self.body_updated.append(answer)
        self._items[answer.id] = answer

    async def get_by_id(self, answer_id: UUID) -> Answer | None:
        return self._items.get(answer_id)

    async def list_by_question(self, question_id: UUID) -> list[Answer]:
        return [a for a in self._items.values() if a.question_id == question_id]


async def test_edit_answer_success_locks_question_and_preserves_state() -> None:
    asker_id = uuid4()
    author_id = uuid4()
    question = Question.ask(title_value="问题标题", body_value="问题正文", author_id=asker_id)
    answer = Answer.post(question_id=question.id, author_id=author_id, body_value="旧回答")
    answer.accept()
    answer.votes_count = 7

    q_repo = _FakeQuestionRepo([question])
    a_repo = _FakeAnswerRepo([answer])
    use_case = EditAnswerUseCase(q_repo, a_repo)

    updated = await use_case.execute(
        EditAnswerCommand(answer_id=answer.id, actor_id=author_id, body="  新回答内容  ")
    )

    assert updated.body.value == "新回答内容"
    assert updated.is_accepted is True
    assert updated.votes_count == 7
    assert q_repo.for_update_calls == [(question.id, True)]
    assert len(a_repo.body_updated) == 1
    assert a_repo.accept_updated == []


async def test_edit_answer_missing_raises_404() -> None:
    use_case = EditAnswerUseCase(_FakeQuestionRepo([]), _FakeAnswerRepo([]))
    with pytest.raises(AnswerNotFoundError):
        await use_case.execute(
            EditAnswerCommand(answer_id=uuid4(), actor_id=uuid4(), body="新内容")
        )


async def test_edit_answer_non_author_raises_403() -> None:
    question = Question.ask(title_value="问题", body_value="正文", author_id=uuid4())
    answer = Answer.post(question_id=question.id, author_id=uuid4(), body_value="原回答")
    q_repo = _FakeQuestionRepo([question])
    a_repo = _FakeAnswerRepo([answer])

    with pytest.raises(NotAnswerAuthorError):
        await EditAnswerUseCase(q_repo, a_repo).execute(
            EditAnswerCommand(answer_id=answer.id, actor_id=question.author_id, body="越权")
        )
    assert a_repo.body_updated == []


async def test_edit_answer_missing_question_raises_404() -> None:
    author_id = uuid4()
    answer = Answer.post(question_id=uuid4(), author_id=author_id, body_value="原回答")
    with pytest.raises(QuestionNotFoundError):
        await EditAnswerUseCase(_FakeQuestionRepo([]), _FakeAnswerRepo([answer])).execute(
            EditAnswerCommand(answer_id=answer.id, actor_id=author_id, body="新内容")
        )


async def test_edit_answer_closed_question_raises_409() -> None:
    author_id = uuid4()
    question = Question.ask(title_value="问题", body_value="正文", author_id=uuid4())
    question.close()
    answer = Answer.post(question_id=question.id, author_id=author_id, body_value="原回答")
    a_repo = _FakeAnswerRepo([answer])

    with pytest.raises(QuestionClosedError):
        await EditAnswerUseCase(_FakeQuestionRepo([question]), a_repo).execute(
            EditAnswerCommand(answer_id=answer.id, actor_id=author_id, body="试图编辑")
        )
    assert a_repo.body_updated == []


@pytest.mark.parametrize("bad_body", ["", "   ", "x" * 5001, "bad\x00body"])
async def test_edit_answer_invalid_body_raises_422(bad_body: str) -> None:
    author_id = uuid4()
    question = Question.ask(title_value="问题", body_value="正文", author_id=uuid4())
    answer = Answer.post(question_id=question.id, author_id=author_id, body_value="原回答")
    a_repo = _FakeAnswerRepo([answer])

    with pytest.raises(DomainValidationError):
        await EditAnswerUseCase(_FakeQuestionRepo([question]), a_repo).execute(
            EditAnswerCommand(answer_id=answer.id, actor_id=author_id, body=bad_body)
        )
    assert a_repo.body_updated == []
