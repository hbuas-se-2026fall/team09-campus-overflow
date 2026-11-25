"""VerifyAnswerUseCase / UnverifyAnswerUseCase 单元测试（不连库，进 CI）。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

import pytest

from app.contexts.qa.application.commands import (
    UnverifyAnswerCommand,
    VerifyAnswerCommand,
)
from app.contexts.qa.application.verify_answer_use_case import (
    UnverifyAnswerUseCase,
    VerifyAnswerUseCase,
)
from app.contexts.qa.domain.answer import Answer
from app.contexts.qa.domain.errors import (
    AnswerNotFoundError,
    QuestionClosedError,
    QuestionNotFoundError,
)
from app.contexts.qa.domain.question import Question
from app.contexts.qa.domain.repository import QuestionFilter, QuestionSort


class _FakeQuestionRepo:
    def __init__(self, questions: list[Question]) -> None:
        self._items = {q.id: q for q in questions}
        self.for_update_calls: list[tuple[UUID, bool]] = []

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
        self.for_update_calls.append((question_id, for_update))
        q = self._items.get(question_id)
        if q is not None and (include_deleted or not q.is_deleted):
            return q
        return None

    async def soft_delete(self, question_id: UUID, deleted_at: datetime) -> bool:
        return False

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
    def __init__(
        self, answers: list[Answer], *, disappear_on_second_read: bool = False
    ) -> None:
        self._items = {a.id: a for a in answers}
        self.verification_updates: list[Answer] = []
        self._disappear_on_second_read = disappear_on_second_read
        self._reads = 0

    async def add(self, answer: Answer) -> None:
        self._items[answer.id] = answer

    async def update(self, answer: Answer) -> None:
        self._items[answer.id] = answer

    async def update_body(self, answer: Answer) -> None:
        self._items[answer.id] = answer

    async def update_verification(self, answer: Answer) -> None:
        self.verification_updates.append(answer)
        self._items[answer.id] = answer

    async def get_by_id(
        self, answer_id: UUID, *, include_deleted: bool = False
    ) -> Answer | None:
        self._reads += 1
        if self._disappear_on_second_read and self._reads >= 2:
            return None
        a = self._items.get(answer_id)
        if a is not None and (include_deleted or not a.is_deleted):
            return a
        return None

    async def soft_delete(self, answer_id: UUID, deleted_at: datetime) -> bool:
        return False

    async def list_by_question(self, question_id: UUID) -> list[Answer]:
        return [a for a in self._items.values() if a.question_id == question_id]


class _FakeNotificationWriter:
    def __init__(self) -> None:
        self.written: list[dict[str, object]] = []

    async def write(
        self,
        *,
        recipient_id: UUID,
        type: str,
        actor_id: UUID,
        target_type: str,
        target_id: UUID,
        source_event_id: UUID,
        question_id: UUID | None = None,
    ) -> None:
        self.written.append(
            {
                "recipient_id": recipient_id,
                "type": type,
                "actor_id": actor_id,
                "target_type": target_type,
                "target_id": target_id,
                "source_event_id": source_event_id,
                "question_id": question_id,
            }
        )


def _sample_qa() -> tuple[Question, Answer]:
    q = Question.ask(
        title_value="B+ 树分裂时父节点键值如何上移？",
        body_value="当叶子节点分裂为左右两半时，为什么需要复制分裂键到父节点？",
        author_id=uuid4(),
    )
    a = Answer.post(
        question_id=q.id,
        author_id=uuid4(),
        body_value=(
            "B+ 树数据指针保存在叶子层，内部节点仅存路由键，叶子分裂需复制分裂键上升。"
        ),
    )
    return q, a


async def test_verify_answer_locks_question_updates_once_and_notifies_author() -> None:
    q, a = _sample_qa()
    teacher_id = uuid4()
    other_ta_id = uuid4()
    q_repo = _FakeQuestionRepo([q])
    a_repo = _FakeAnswerRepo([a])
    notifier = _FakeNotificationWriter()

    use_case = VerifyAnswerUseCase(q_repo, a_repo, notifier)
    verified = await use_case.execute(
        VerifyAnswerCommand(answer_id=a.id, actor_id=teacher_id)
    )
    assert verified.is_teacher_verified is True
    assert verified.verified_by == teacher_id
    assert verified.verified_at is not None
    assert q_repo.for_update_calls == [(q.id, True)]
    assert len(a_repo.verification_updates) == 1
    assert len(notifier.written) == 1
    assert notifier.written[0]["recipient_id"] == a.author_id
    assert notifier.written[0]["type"] == "answer_verified"
    assert notifier.written[0]["actor_id"] == teacher_id
    assert notifier.written[0]["target_type"] == "answer"
    assert notifier.written[0]["target_id"] == a.id
    assert notifier.written[0]["question_id"] == q.id

    # 重复认证：幂等保留首次认证人与时间，不再写库也不再发通知
    repeat = await use_case.execute(
        VerifyAnswerCommand(answer_id=a.id, actor_id=other_ta_id)
    )
    assert repeat.verified_by == teacher_id
    assert repeat.verified_at == verified.verified_at
    assert len(a_repo.verification_updates) == 1
    assert len(notifier.written) == 1


async def test_verify_self_answer_skips_notification() -> None:
    q, a = _sample_qa()
    notifier = _FakeNotificationWriter()
    a_repo = _FakeAnswerRepo([a])
    use_case = VerifyAnswerUseCase(_FakeQuestionRepo([q]), a_repo, notifier)

    verified = await use_case.execute(
        VerifyAnswerCommand(answer_id=a.id, actor_id=a.author_id)
    )
    assert verified.is_teacher_verified is True
    assert len(a_repo.verification_updates) == 1
    assert notifier.written == []


async def test_verify_and_unverify_error_branches() -> None:
    q, a = _sample_qa()
    actor = uuid4()

    # 回答不存在 → 404
    with pytest.raises(AnswerNotFoundError):
        await VerifyAnswerUseCase(_FakeQuestionRepo([q]), _FakeAnswerRepo([])).execute(
            VerifyAnswerCommand(answer_id=uuid4(), actor_id=actor)
        )
    with pytest.raises(AnswerNotFoundError):
        await UnverifyAnswerUseCase(_FakeQuestionRepo([q]), _FakeAnswerRepo([])).execute(
            UnverifyAnswerCommand(answer_id=uuid4())
        )

    # 父问题不存在 → 404
    with pytest.raises(QuestionNotFoundError):
        await VerifyAnswerUseCase(_FakeQuestionRepo([]), _FakeAnswerRepo([a])).execute(
            VerifyAnswerCommand(answer_id=a.id, actor_id=actor)
        )

    # 锁父问题后重读回答消失（并发软删除窗口）→ 404
    with pytest.raises(AnswerNotFoundError):
        await VerifyAnswerUseCase(
            _FakeQuestionRepo([q]),
            _FakeAnswerRepo([a], disappear_on_second_read=True),
        ).execute(VerifyAnswerCommand(answer_id=a.id, actor_id=actor))

    # 已关闭问题 → 409
    q.close()
    a_repo = _FakeAnswerRepo([a])
    notifier = _FakeNotificationWriter()
    with pytest.raises(QuestionClosedError):
        await VerifyAnswerUseCase(_FakeQuestionRepo([q]), a_repo, notifier).execute(
            VerifyAnswerCommand(answer_id=a.id, actor_id=actor)
        )
    with pytest.raises(QuestionClosedError):
        await UnverifyAnswerUseCase(_FakeQuestionRepo([q]), a_repo).execute(
            UnverifyAnswerCommand(answer_id=a.id)
        )
    assert a_repo.verification_updates == []
    assert notifier.written == []


async def test_unverify_answer_clears_and_is_idempotent() -> None:
    q, a = _sample_qa()
    a.verify(uuid4())
    q_repo = _FakeQuestionRepo([q])
    a_repo = _FakeAnswerRepo([a])
    use_case = UnverifyAnswerUseCase(q_repo, a_repo)

    await use_case.execute(UnverifyAnswerCommand(answer_id=a.id))
    assert a.is_teacher_verified is False
    assert a.verified_by is None
    assert a.verified_at is None
    assert len(a_repo.verification_updates) == 1
    assert q_repo.for_update_calls == [(q.id, True)]

    # 幂等取消：不再触发写库
    await use_case.execute(UnverifyAnswerCommand(answer_id=a.id))
    assert len(a_repo.verification_updates) == 1
