"""qa 通知钩子单测（F04）：三类事件写入时机、收件人、自操作不通知。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

from app.contexts.qa.application.accept_use_case import AcceptAnswerUseCase
from app.contexts.qa.application.answer_use_case import PostAnswerUseCase
from app.contexts.qa.application.commands import (
    AcceptAnswerCommand,
    CreateCommentCommand,
    PostAnswerCommand,
)
from app.contexts.qa.application.comment_use_case import CreateCommentUseCase
from app.contexts.qa.domain.answer import Answer
from app.contexts.qa.domain.comment import CommentTarget
from app.contexts.qa.domain.question import Question
from app.contexts.qa.domain.value_objects import Body, Title


class FakeWriter:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def write(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


class FakeQuestionRepository:
    def __init__(self, question: Question) -> None:
        self.question = question

    async def get_by_id(
        self,
        question_id: UUID,
        *,
        for_update: bool = False,
        include_deleted: bool = False,
    ) -> Question | None:
        if self.question.id == question_id and (
            include_deleted or not self.question.is_deleted
        ):
            return self.question
        return None

    async def update(self, question: Question) -> None:
        self.question = question

    async def soft_delete(self, question_id: UUID, deleted_at: datetime) -> bool:
        return False


class FakeAnswerRepository:
    def __init__(self, answer: Answer | None = None) -> None:
        self.answer = answer

    async def get_by_id(
        self, answer_id: UUID, *, include_deleted: bool = False
    ) -> Answer | None:
        if (
            self.answer is not None
            and self.answer.id == answer_id
            and (include_deleted or not self.answer.is_deleted)
        ):
            return self.answer
        return None

    async def add(self, answer: Answer) -> None:
        self.answer = answer

    async def update(self, answer: Answer) -> None:
        self.answer = answer

    async def update_body(self, answer: Answer) -> None:
        self.answer = answer

    async def soft_delete(self, answer_id: UUID, deleted_at: datetime) -> bool:
        return False


class FakeCommentRepository:
    async def add(self, comment: object) -> None:
        return None


def _question(author_id: UUID) -> Question:
    return Question(
        id=uuid4(),
        title=Title("通知钩子测试"),
        body=Body("F04 通知钩子：验证收件人与自操作过滤。"),
        author_id=author_id,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _answer(question: Question, author_id: UUID) -> Answer:
    return Answer(
        id=uuid4(),
        question_id=question.id,
        author_id=author_id,
        body=Body("回答正文"),
        created_at=datetime(2026, 1, 2, tzinfo=UTC),
    )


async def test_answer_notifies_question_author() -> None:
    asker, responder = uuid4(), uuid4()
    question = _question(asker)
    writer = FakeWriter()
    use_case = PostAnswerUseCase(
        FakeQuestionRepository(question), FakeAnswerRepository(), writer
    )
    answer = await use_case.execute(
        PostAnswerCommand(question_id=question.id, body="回答正文", author_id=responder)
    )
    assert len(writer.calls) == 1
    call = writer.calls[0]
    assert call["recipient_id"] == asker
    assert call["actor_id"] == responder
    assert call["type"] == "answer_posted"
    assert call["target_id"] == question.id
    assert call["source_event_id"] == answer.id
    assert call["question_id"] == question.id


async def test_self_answer_does_not_notify() -> None:
    asker = uuid4()
    question = _question(asker)
    writer = FakeWriter()
    use_case = PostAnswerUseCase(
        FakeQuestionRepository(question), FakeAnswerRepository(), writer
    )
    await use_case.execute(
        PostAnswerCommand(question_id=question.id, body="自答", author_id=asker)
    )
    assert writer.calls == []


async def test_comment_notifies_host_author_but_not_self() -> None:
    author, commenter = uuid4(), uuid4()
    question = _question(author)
    writer = FakeWriter()
    use_case = CreateCommentUseCase(
        FakeQuestionRepository(question),
        FakeAnswerRepository(),
        FakeCommentRepository(),  # type: ignore[arg-type]
        writer,
    )
    comment = await use_case.execute(
        CreateCommentCommand(
            target_type=CommentTarget.QUESTION,
            target_id=question.id,
            body="评论正文",
            author_id=commenter,
        )
    )
    assert len(writer.calls) == 1
    assert writer.calls[0]["recipient_id"] == author
    assert writer.calls[0]["type"] == "comment_created"
    assert writer.calls[0]["source_event_id"] == comment.id
    assert writer.calls[0]["question_id"] == question.id

    writer.calls.clear()
    await use_case.execute(
        CreateCommentCommand(
            target_type=CommentTarget.QUESTION,
            target_id=question.id,
            body="自评",
            author_id=author,
        )
    )
    assert writer.calls == []


async def test_answer_comment_notifies_answer_author() -> None:
    asker, responder, commenter = uuid4(), uuid4(), uuid4()
    question = _question(asker)
    answer = _answer(question, responder)
    writer = FakeWriter()
    use_case = CreateCommentUseCase(
        FakeQuestionRepository(question),
        FakeAnswerRepository(answer),
        FakeCommentRepository(),  # type: ignore[arg-type]
        writer,
    )
    await use_case.execute(
        CreateCommentCommand(
            target_type=CommentTarget.ANSWER,
            target_id=answer.id,
            body="答评正文",
            author_id=commenter,
        )
    )
    assert writer.calls[0]["recipient_id"] == responder
    assert writer.calls[0]["target_type"] == "answer"
    assert writer.calls[0]["question_id"] == question.id


async def test_accept_notifies_answer_author_once() -> None:
    asker, responder = uuid4(), uuid4()
    question = _question(asker)
    answer = _answer(question, responder)
    writer = FakeWriter()
    use_case = AcceptAnswerUseCase(
        FakeQuestionRepository(question), FakeAnswerRepository(answer), writer
    )
    outcome = await use_case.execute(
        AcceptAnswerCommand(answer_id=answer.id, actor_id=asker)
    )
    assert len(writer.calls) == 1
    assert writer.calls[0]["recipient_id"] == responder
    assert writer.calls[0]["type"] == "answer_accepted"
    assert writer.calls[0]["source_event_id"] == outcome.event.event_id
    assert writer.calls[0]["question_id"] == question.id


async def test_self_accept_does_not_notify() -> None:
    asker = uuid4()
    question = _question(asker)
    answer = _answer(question, asker)  # 提问者自己的回答
    writer = FakeWriter()
    use_case = AcceptAnswerUseCase(
        FakeQuestionRepository(question), FakeAnswerRepository(answer), writer
    )
    await use_case.execute(AcceptAnswerCommand(answer_id=answer.id, actor_id=asker))
    assert writer.calls == []
