"""发起悬赏用例单测（F07 加固）：已采纳/已关闭拦截与 for_update 行锁请求。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.contexts.qa.application.bounty_service import BountyService
from app.contexts.qa.application.commands import CreateBountyCommand
from app.contexts.qa.application.create_bounty_use_case import CreateBountyUseCase
from app.contexts.qa.domain.bounty import Bounty, BountyStatus
from app.contexts.qa.domain.errors import (
    AnswerAlreadyAcceptedError,
    QuestionClosedError,
    QuestionNotFoundError,
)
from app.contexts.qa.domain.question import Question, QuestionStatus
from app.contexts.qa.domain.value_objects import Body, Title


class FakeQuestionRepository:
    def __init__(self, question: Question | None) -> None:
        self.question = question
        self.for_update_calls: list[bool] = []

    async def add(self, question: Question) -> None:
        self.question = question

    async def update(self, question: Question) -> None:
        self.question = question

    async def get_by_id(
        self,
        question_id: UUID,
        *,
        for_update: bool = False,
        include_deleted: bool = False,
    ) -> Question | None:
        self.for_update_calls.append(for_update)
        if (
            self.question is not None
            and self.question.id == question_id
            and (include_deleted or not self.question.is_deleted)
        ):
            return self.question
        return None

    async def soft_delete(self, question_id: UUID, deleted_at: datetime) -> bool:
        return False

    async def list_related(self, question_id: UUID, limit: int) -> list[Question]:
        return []

    async def list_paginated(
        self, page: int, page_size: int, sort: object = None, filters: object = None
    ) -> tuple[list[Question], int]:
        return [], 0


class SpyBountyService:
    def __init__(self) -> None:
        self.calls: list[tuple[UUID, UUID, int]] = []

    async def create(self, question_id: UUID, teacher_id: UUID, amount: int) -> Bounty:
        self.calls.append((question_id, teacher_id, amount))
        return Bounty(
            id=uuid4(),
            question_id=question_id,
            teacher_id=teacher_id,
            amount=amount,
            status=BountyStatus.OPEN,
            created_at=datetime.now(UTC),
            settled_at=None,
        )


def _question(
    *,
    status: QuestionStatus = QuestionStatus.OPEN,
    accepted_answer_id: UUID | None = None,
) -> Question:
    return Question(
        id=uuid4(),
        title=Title("悬赏用例测试问题"),
        body=Body("测试已采纳/已关闭拦截与 for_update 行锁参数。"),
        author_id=uuid4(),
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        accepted_answer_id=accepted_answer_id,
        status=status,
    )


async def test_create_bounty_rejects_missing_question() -> None:
    service = SpyBountyService()
    use_case = CreateBountyUseCase(
        FakeQuestionRepository(None),
        service,  # type: ignore[arg-type]
    )
    with pytest.raises(QuestionNotFoundError):
        await use_case.execute(
            CreateBountyCommand(question_id=uuid4(), teacher_id=uuid4(), amount=10)
        )
    assert service.calls == []


async def test_create_bounty_rejects_already_accepted_question() -> None:
    question = _question(accepted_answer_id=uuid4())
    repo = FakeQuestionRepository(question)
    service = SpyBountyService()
    use_case = CreateBountyUseCase(repo, service)  # type: ignore[arg-type]

    with pytest.raises(AnswerAlreadyAcceptedError):
        await use_case.execute(
            CreateBountyCommand(question_id=question.id, teacher_id=uuid4(), amount=20)
        )
    assert repo.for_update_calls == [True]
    assert service.calls == []


async def test_create_bounty_rejects_closed_question() -> None:
    question = _question(status=QuestionStatus.CLOSED)
    repo = FakeQuestionRepository(question)
    service = SpyBountyService()
    use_case = CreateBountyUseCase(repo, service)  # type: ignore[arg-type]

    with pytest.raises(QuestionClosedError):
        await use_case.execute(
            CreateBountyCommand(question_id=question.id, teacher_id=uuid4(), amount=20)
        )
    assert repo.for_update_calls == [True]
    assert service.calls == []


async def test_create_bounty_locks_open_question_and_calls_service() -> None:
    question = _question()
    repo = FakeQuestionRepository(question)
    service = SpyBountyService()
    assert isinstance(BountyService, type)
    teacher_id = uuid4()
    use_case = CreateBountyUseCase(repo, service)  # type: ignore[arg-type]

    bounty = await use_case.execute(
        CreateBountyCommand(question_id=question.id, teacher_id=teacher_id, amount=25)
    )
    assert repo.for_update_calls == [True]
    assert service.calls == [(question.id, teacher_id, 25)]
    assert bounty.amount == 25
