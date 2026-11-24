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
from app.contexts.qa.domain.comment import Comment, CommentTarget
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
    def __init__(self, initial: list[Comment] | None = None) -> None:
        self.added: list[Comment] = list(initial or [])

    async def add(self, comment: Comment) -> None:
        self.added.append(comment)

    async def get_by_id(self, comment_id: UUID) -> Comment | None:
        return next((c for c in self.added if c.id == comment_id), None)

    async def list_by_target(
        self, target_type: CommentTarget, target_id: UUID
    ) -> list[Comment]:
        return [
            c
            for c in self.added
            if c.target_type == target_type and c.target_id == target_id
        ]


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
        FakeCommentRepository(),
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
        FakeCommentRepository(),
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


async def test_reply_notifies_parent_author_and_host_author_separately() -> None:
    """F14 D4：第三方回复一级评论，分别通知父评论作者与宿主作者。"""
    asker, parent_author, replier = uuid4(), uuid4(), uuid4()
    question = _question(asker)
    parent = Comment.write(
        target_type=CommentTarget.QUESTION,
        target_id=question.id,
        author_id=parent_author,
        body_value="父评论",
    )
    writer = FakeWriter()
    use_case = CreateCommentUseCase(
        FakeQuestionRepository(question),
        FakeAnswerRepository(),
        FakeCommentRepository([parent]),
        writer,
    )
    reply = await use_case.execute(
        CreateCommentCommand(
            target_type=CommentTarget.QUESTION,
            target_id=question.id,
            body="二级回复",
            author_id=replier,
            parent_id=parent.id,
        )
    )
    assert len(writer.calls) == 2
    assert writer.calls[0] == {
        "recipient_id": parent_author,
        "type": "comment_replied",
        "actor_id": replier,
        "target_type": "comment",
        "target_id": parent.id,
        "source_event_id": reply.id,
        "question_id": question.id,
    }
    assert writer.calls[1] == {
        "recipient_id": asker,
        "type": "comment_created",
        "actor_id": replier,
        "target_type": "question",
        "target_id": question.id,
        "source_event_id": reply.id,
        "question_id": question.id,
    }


async def test_reply_deduplicates_when_host_author_equals_parent_author() -> None:
    """F14 D4：宿主作者与父评论作者为同一人时，只发 1 条 comment_replied。"""
    asker, replier = uuid4(), uuid4()
    question = _question(asker)
    parent = Comment.write(
        target_type=CommentTarget.QUESTION,
        target_id=question.id,
        author_id=asker,
        body_value="提问者自己的一级评论",
    )
    writer = FakeWriter()
    use_case = CreateCommentUseCase(
        FakeQuestionRepository(question),
        FakeAnswerRepository(),
        FakeCommentRepository([parent]),
        writer,
    )
    reply = await use_case.execute(
        CreateCommentCommand(
            target_type=CommentTarget.QUESTION,
            target_id=question.id,
            body="他人回复提问者的评论",
            author_id=replier,
            parent_id=parent.id,
        )
    )
    assert len(writer.calls) == 1
    assert writer.calls[0]["recipient_id"] == asker
    assert writer.calls[0]["type"] == "comment_replied"
    assert writer.calls[0]["target_type"] == "comment"
    assert writer.calls[0]["target_id"] == parent.id
    assert writer.calls[0]["source_event_id"] == reply.id


async def test_reply_self_operations_and_answer_reply_routing() -> None:
    """F14 D4：自回复跳过 comment_replied（仍通知不同宿主作者）；答评回复路由到答主与父评作者。"""
    asker, answerer, commenter, replier = uuid4(), uuid4(), uuid4(), uuid4()
    question = _question(asker)
    answer = _answer(question, answerer)
    ans_parent = Comment.write(
        target_type=CommentTarget.ANSWER,
        target_id=answer.id,
        author_id=commenter,
        body_value="一级答评",
    )
    writer = FakeWriter()
    use_case = CreateCommentUseCase(
        FakeQuestionRepository(question),
        FakeAnswerRepository(answer),
        FakeCommentRepository([ans_parent]),
        writer,
    )

    # 1. commenter 回复自己的一级答评：跳过对自己的 comment_replied，但通知答主 comment_created
    await use_case.execute(
        CreateCommentCommand(
            target_type=CommentTarget.ANSWER,
            target_id=answer.id,
            body="补充自己的一级答评",
            author_id=commenter,
            parent_id=ans_parent.id,
        )
    )
    assert len(writer.calls) == 1
    assert writer.calls[0]["recipient_id"] == answerer
    assert writer.calls[0]["type"] == "comment_created"
    assert writer.calls[0]["target_type"] == "answer"
    assert writer.calls[0]["target_id"] == answer.id
    assert writer.calls[0]["question_id"] == question.id

    # 2. 答主回复 commenter 的一级答评：通知 commenter comment_replied，跳过答主自己
    writer.calls.clear()
    await use_case.execute(
        CreateCommentCommand(
            target_type=CommentTarget.ANSWER,
            target_id=answer.id,
            body="答主回复评论",
            author_id=answerer,
            parent_id=ans_parent.id,
        )
    )
    assert len(writer.calls) == 1
    assert writer.calls[0]["recipient_id"] == commenter
    assert writer.calls[0]["type"] == "comment_replied"
    assert writer.calls[0]["target_type"] == "comment"
    assert writer.calls[0]["target_id"] == ans_parent.id
    assert writer.calls[0]["question_id"] == question.id

    # 3. 第三方 replier 回复 commenter 的一级答评：通知 commenter(replied) + answerer(created)
    writer.calls.clear()
    await use_case.execute(
        CreateCommentCommand(
            target_type=CommentTarget.ANSWER,
            target_id=answer.id,
            body="第三方追问答评",
            author_id=replier,
            parent_id=ans_parent.id,
        )
    )
    assert len(writer.calls) == 2
    assert {(c["recipient_id"], c["type"], c["target_type"]) for c in writer.calls} == {
        (commenter, "comment_replied", "comment"),
        (answerer, "comment_created", "answer"),
    }
    assert all(c["question_id"] == question.id for c in writer.calls)

    # 4. 宿主作者回复自己的一级题评：0 通知
    q_self_parent = Comment.write(
        target_type=CommentTarget.QUESTION,
        target_id=question.id,
        author_id=asker,
        body_value="题主一级评",
    )
    writer.calls.clear()
    q_uc = CreateCommentUseCase(
        FakeQuestionRepository(question),
        FakeAnswerRepository(answer),
        FakeCommentRepository([q_self_parent]),
        writer,
    )
    await q_uc.execute(
        CreateCommentCommand(
            target_type=CommentTarget.QUESTION,
            target_id=question.id,
            body="题主自回复",
            author_id=asker,
            parent_id=q_self_parent.id,
        )
    )
    assert writer.calls == []
