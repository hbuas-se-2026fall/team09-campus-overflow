"""回答用例：发布回答（US-A01）。"""

from __future__ import annotations

from app.contexts.qa.application.commands import PostAnswerCommand
from app.contexts.qa.application.ports import NotificationWriter
from app.contexts.qa.domain.answer import Answer
from app.contexts.qa.domain.errors import QuestionNotFoundError
from app.contexts.qa.domain.repository import AnswerRepository, QuestionRepository


class PostAnswerUseCase:
    """回答用例：先确认目标问题存在（不存在→404），已关闭→409（A01 不变式，迭代 5 落地），
    再构造 Answer 聚合（Body 值对象即校验，失败→ValueError→422）并落库。

    F04：同事务写"我的问题有新回答"通知（提问者 ≠ 回答者时）。
    """

    def __init__(
        self,
        question_repository: QuestionRepository,
        answer_repository: AnswerRepository,
        notification_writer: NotificationWriter | None = None,
    ) -> None:
        self._question_repository = question_repository
        self._answer_repository = answer_repository
        self._notification_writer = notification_writer

    async def execute(self, command: PostAnswerCommand) -> Answer:
        question = await self._question_repository.get_by_id(command.question_id)
        if question is None:
            raise QuestionNotFoundError("问题不存在")
        question.ensure_open("新增回答")
        answer = Answer.post(
            question_id=command.question_id,
            author_id=command.author_id,
            body_value=command.body,
        )
        await self._answer_repository.add(answer)
        if (
            self._notification_writer is not None
            and question.author_id != answer.author_id
        ):
            await self._notification_writer.write(
                recipient_id=question.author_id,
                type="answer_posted",
                actor_id=answer.author_id,
                target_type="question",
                target_id=question.id,
                source_event_id=answer.id,
                question_id=question.id,
            )
        return answer