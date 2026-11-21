"""DeleteQuestionUseCase / DeleteAnswerUseCase 单元测试（F13，fake 仓储，不连库，进 CI）。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import pytest

from app.contexts.qa.application.commands import (
    DeleteAnswerCommand,
    DeleteQuestionCommand,
)
from app.contexts.qa.application.delete_answer_use_case import DeleteAnswerUseCase
from app.contexts.qa.application.delete_question_use_case import DeleteQuestionUseCase
from app.contexts.qa.domain.answer import Answer
from app.contexts.qa.domain.errors import (
    AcceptedAnswerCannotDeleteError,
    AnswerNotFoundError,
    NotAnswerAuthorError,
    NotQuestionAuthorError,
    QuestionNotFoundError,
)
from app.contexts.qa.domain.question import Question
from app.contexts.qa.domain.repository import QuestionFilter, QuestionSort


class _FakeQuestionRepo:
    def __init__(self, questions: list[Question]) -> None:
        self._items = {q.id: q for q in questions}
        self.get_calls: list[tuple[UUID, bool, bool]] = []
        self.soft_delete_calls: list[tuple[UUID, datetime]] = []

    async def add(self, question: Question) -> None:
        self._items[question.id] = question

    async def update(self, question: Question) -> None:
        self._items[question.id] = question

    async def get_by_id(
        self,
        question_id: UUID,
        *,
        for_update: bool = False,
        include_deleted: bool = False,
    ) -> Question | None:
        self.get_calls.append((question_id, for_update, include_deleted))
        q = self._items.get(question_id)
        if q is not None and (include_deleted or not q.is_deleted):
            return q
        return None

    async def soft_delete(self, question_id: UUID, deleted_at: datetime) -> bool:
        self.soft_delete_calls.append((question_id, deleted_at))
        q = self._items.get(question_id)
        if q is None:
            raise QuestionNotFoundError("问题不存在")
        if q.accepted_answer_id is not None:
            raise AcceptedAnswerCannotDeleteError("该问题已有采纳答案，不可删除")
        q.deleted_at = deleted_at
        return True

    async def list_related(self, question_id: UUID, limit: int) -> list[Question]:
        return []

    async def list_paginated(
        self,
        page: int,
        page_size: int,
        sort: QuestionSort = QuestionSort.LATEST,
        filters: QuestionFilter | None = None,
    ) -> tuple[list[Question], int]:
        items = [q for q in self._items.values() if not q.is_deleted]
        return items, len(items)


class _FakeAnswerRepo:
    def __init__(self, answers: list[Answer]) -> None:
        self._items = {a.id: a for a in answers}
        self.get_calls: list[tuple[UUID, bool]] = []
        self.soft_delete_calls: list[tuple[UUID, datetime]] = []

    async def add(self, answer: Answer) -> None:
        self._items[answer.id] = answer

    async def update(self, answer: Answer) -> None:
        self._items[answer.id] = answer

    async def update_body(self, answer: Answer) -> None:
        self._items[answer.id] = answer

    async def get_by_id(
        self, answer_id: UUID, *, include_deleted: bool = False
    ) -> Answer | None:
        self.get_calls.append((answer_id, include_deleted))
        a = self._items.get(answer_id)
        if a is not None and (include_deleted or not a.is_deleted):
            return a
        return None

    async def soft_delete(self, answer_id: UUID, deleted_at: datetime) -> bool:
        self.soft_delete_calls.append((answer_id, deleted_at))
        a = self._items.get(answer_id)
        if a is None:
            raise AnswerNotFoundError("回答不存在")
        if a.is_accepted:
            raise AcceptedAnswerCannotDeleteError("已采纳的回答不可删除")
        a.deleted_at = deleted_at
        return True

    async def list_by_question(self, question_id: UUID) -> list[Answer]:
        return [
            a
            for a in self._items.values()
            if a.question_id == question_id and not a.is_deleted
        ]


class _SpyBountyService:
    def __init__(self) -> None:
        self.refunded_questions: list[UUID] = []

    async def refund_on_delete(self, question_id: UUID) -> bool:
        self.refunded_questions.append(question_id)
        return True


def _make_question(*, author_id: UUID | None = None) -> Question:
    return Question.ask(
        title_value="PostgreSQL 中 VACUUM 如何借助可见性映射清理 B-Tree 死索引项？",
        body_value="当表堆发生频繁 UPDATE 时，B-Tree 索引中的旧 TID 何时被回收复用？",
        author_id=author_id or uuid4(),
    )


def _make_answer(question_id: UUID, *, author_id: UUID | None = None) -> Answer:
    return Answer.post(
        question_id=question_id,
        author_id=author_id or uuid4(),
        body_value=(
            "VACUUM 扫描未标记 all-visible 的堆页收集死元组 TID，随后遍历 B-Tree 回收索引槽位。"
        ),
    )


# ---------------- DeleteQuestionUseCase ----------------


async def test_delete_question_by_author_soft_deletes_and_refunds_bounty_once() -> None:
    asker_id = uuid4()
    question = _make_question(author_id=asker_id)
    q_repo = _FakeQuestionRepo([question])
    bounty_spy = _SpyBountyService()
    use_case = DeleteQuestionUseCase(q_repo, bounty_spy)  # type: ignore[arg-type]

    await use_case.execute(
        DeleteQuestionCommand(question_id=question.id, actor_id=asker_id)
    )

    assert question.is_deleted is True
    assert q_repo.get_calls == [(question.id, True, True)]
    assert len(q_repo.soft_delete_calls) == 1
    assert bounty_spy.refunded_questions == [question.id]

    # D1/D3：作者重复删除幂等返回，不再次调用仓储 soft_delete，也不二次退悬赏
    await use_case.execute(
        DeleteQuestionCommand(question_id=question.id, actor_id=asker_id)
    )
    assert len(q_repo.soft_delete_calls) == 1
    assert bounty_spy.refunded_questions == [question.id]


async def test_delete_closed_question_by_author_allowed() -> None:
    asker_id = uuid4()
    question = _make_question(author_id=asker_id)
    question.close()
    q_repo = _FakeQuestionRepo([question])

    await DeleteQuestionUseCase(q_repo).execute(
        DeleteQuestionCommand(question_id=question.id, actor_id=asker_id)
    )

    assert question.is_deleted is True
    assert len(q_repo.soft_delete_calls) == 1


async def test_delete_question_missing_or_deleted_by_non_author_raises_404() -> None:
    asker_id = uuid4()
    other_id = uuid4()
    question = _make_question(author_id=asker_id)
    question.soft_delete()
    q_repo = _FakeQuestionRepo([question])
    use_case = DeleteQuestionUseCase(q_repo)

    # 不存在的问题 → 404
    with pytest.raises(QuestionNotFoundError):
        await use_case.execute(
            DeleteQuestionCommand(question_id=uuid4(), actor_id=other_id)
        )

    # 已软删除的问题对非作者 → 404（不返回 403，防止泄露存在性）
    with pytest.raises(QuestionNotFoundError):
        await use_case.execute(
            DeleteQuestionCommand(question_id=question.id, actor_id=other_id)
        )
    assert q_repo.soft_delete_calls == []


async def test_delete_question_403_precedes_409_and_author_accepted_raises_409() -> None:
    asker_id = uuid4()
    other_id = uuid4()
    question = _make_question(author_id=asker_id)
    question.mark_accepted(uuid4())
    q_repo = _FakeQuestionRepo([question])
    use_case = DeleteQuestionUseCase(q_repo)

    # D1 补充：活跃内容上非作者尝试删除已采纳问题 → 403 优先于 409
    with pytest.raises(NotQuestionAuthorError):
        await use_case.execute(
            DeleteQuestionCommand(question_id=question.id, actor_id=other_id)
        )

    # 作者本人尝试删除已有采纳答案的问题 → 409（D2=B）
    with pytest.raises(AcceptedAnswerCannotDeleteError):
        await use_case.execute(
            DeleteQuestionCommand(question_id=question.id, actor_id=asker_id)
        )
    assert question.is_deleted is False
    assert q_repo.soft_delete_calls == []


# ---------------- DeleteAnswerUseCase ----------------


async def test_delete_answer_by_author_locks_parent_and_is_idempotent() -> None:
    question = _make_question()
    answer_author = uuid4()
    answer = _make_answer(question.id, author_id=answer_author)
    q_repo = _FakeQuestionRepo([question])
    a_repo = _FakeAnswerRepo([answer])
    use_case = DeleteAnswerUseCase(q_repo, a_repo)

    await use_case.execute(
        DeleteAnswerCommand(answer_id=answer.id, actor_id=answer_author)
    )

    assert answer.is_deleted is True
    assert q_repo.get_calls == [(question.id, True, True)]
    assert a_repo.get_calls == [(answer.id, True), (answer.id, True)]
    assert len(a_repo.soft_delete_calls) == 1

    # 父问题仍活跃时，作者重复删除幂等返回 204
    await use_case.execute(
        DeleteAnswerCommand(answer_id=answer.id, actor_id=answer_author)
    )
    assert len(a_repo.soft_delete_calls) == 1


async def test_delete_answer_under_closed_question_allowed() -> None:
    question = _make_question()
    question.close()
    answer_author = uuid4()
    answer = _make_answer(question.id, author_id=answer_author)
    q_repo = _FakeQuestionRepo([question])
    a_repo = _FakeAnswerRepo([answer])

    await DeleteAnswerUseCase(q_repo, a_repo).execute(
        DeleteAnswerCommand(answer_id=answer.id, actor_id=answer_author)
    )

    assert answer.is_deleted is True
    assert len(a_repo.soft_delete_calls) == 1


async def test_delete_answer_when_parent_deleted_raises_404_for_author_and_non_author() -> None:
    question = _make_question()
    question.soft_delete()
    answer_author = uuid4()
    answer = _make_answer(question.id, author_id=answer_author)
    q_repo = _FakeQuestionRepo([question])
    a_repo = _FakeAnswerRepo([answer])
    use_case = DeleteAnswerUseCase(q_repo, a_repo)

    # D1/D4：父问题已删时，无论答主还是非作者均返回 404（非作者绝不返回 403）
    for actor in (answer_author, uuid4()):
        with pytest.raises(QuestionNotFoundError):
            await use_case.execute(
                DeleteAnswerCommand(answer_id=answer.id, actor_id=actor)
            )
    assert a_repo.soft_delete_calls == []


async def test_delete_answer_missing_or_deleted_by_non_author_raises_404() -> None:
    question = _make_question()
    answer_author = uuid4()
    answer = _make_answer(question.id, author_id=answer_author)
    answer.soft_delete()
    q_repo = _FakeQuestionRepo([question])
    a_repo = _FakeAnswerRepo([answer])
    use_case = DeleteAnswerUseCase(q_repo, a_repo)

    with pytest.raises(AnswerNotFoundError):
        await use_case.execute(
            DeleteAnswerCommand(answer_id=uuid4(), actor_id=answer_author)
        )

    with pytest.raises(AnswerNotFoundError):
        await use_case.execute(
            DeleteAnswerCommand(answer_id=answer.id, actor_id=uuid4())
        )
    assert a_repo.soft_delete_calls == []


async def test_delete_answer_403_precedes_409_and_accepted_raises_409() -> None:
    question = _make_question()
    answer_author = uuid4()
    answer = _make_answer(question.id, author_id=answer_author)
    answer.accept()
    q_repo = _FakeQuestionRepo([question])
    a_repo = _FakeAnswerRepo([answer])
    use_case = DeleteAnswerUseCase(q_repo, a_repo)

    # 非作者尝试删已采纳回答 → 403 优先于 409
    with pytest.raises(NotAnswerAuthorError):
        await use_case.execute(
            DeleteAnswerCommand(answer_id=answer.id, actor_id=uuid4())
        )

    # 作者本人尝试删已采纳回答 → 409
    with pytest.raises(AcceptedAnswerCannotDeleteError):
        await use_case.execute(
            DeleteAnswerCommand(answer_id=answer.id, actor_id=answer_author)
        )
    assert answer.is_deleted is False
    assert a_repo.soft_delete_calls == []


async def test_delete_answer_rereads_after_parent_lock_catches_concurrent_accept() -> None:
    """F13 D4 补充：若等待父问题行锁期间回答被提问者采纳，重读 Answer 后必须拦截并抛 409。"""
    question = _make_question()
    answer_author = uuid4()
    answer = _make_answer(question.id, author_id=answer_author)
    q_repo = _FakeQuestionRepo([question])
    a_repo = _FakeAnswerRepo([answer])

    orig_q_get = q_repo.get_by_id

    async def _accept_during_parent_lock(
        question_id: UUID,
        *,
        for_update: bool = False,
        include_deleted: bool = False,
    ) -> Question | None:
        answer.accept()
        question.mark_accepted(answer.id)
        return await orig_q_get(
            question_id, for_update=for_update, include_deleted=include_deleted
        )

    q_repo.get_by_id = _accept_during_parent_lock  # type: ignore[method-assign]

    with pytest.raises(AcceptedAnswerCannotDeleteError):
        await DeleteAnswerUseCase(q_repo, a_repo).execute(
            DeleteAnswerCommand(answer_id=answer.id, actor_id=answer_author)
        )
    assert a_repo.soft_delete_calls == []
