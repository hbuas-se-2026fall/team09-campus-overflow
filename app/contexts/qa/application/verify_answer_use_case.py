"""教师/助教/管理员认证与取消认证回答用例（F15 D3）。"""

from __future__ import annotations

from uuid import UUID, uuid4

from app.contexts.qa.application.commands import (
    UnverifyAnswerCommand,
    VerifyAnswerCommand,
)
from app.contexts.qa.application.ports import NotificationWriter
from app.contexts.qa.domain.answer import Answer
from app.contexts.qa.domain.errors import AnswerNotFoundError, QuestionNotFoundError
from app.contexts.qa.domain.question import Question
from app.contexts.qa.domain.repository import AnswerRepository, QuestionRepository


async def _load_for_verification_change(
    question_repository: QuestionRepository,
    answer_repository: AnswerRepository,
    answer_id: UUID,
    action_label: str,
) -> tuple[Question, Answer]:
    """统一单根无环锁序：无锁读 Answer → 锁父 Question → 重读 Answer → 校验 open 态。"""
    answer = await answer_repository.get_by_id(answer_id)
    if answer is None:
        raise AnswerNotFoundError("回答不存在")
    question = await question_repository.get_by_id(answer.question_id, for_update=True)
    if question is None:
        raise QuestionNotFoundError("问题不存在")
    answer = await answer_repository.get_by_id(answer_id)
    if answer is None:
        raise AnswerNotFoundError("回答不存在")
    question.ensure_open(action_label)
    return question, answer


class VerifyAnswerUseCase:
    """认证回答：幂等置位并仅在首次变为已认证且非自操作时同事务发站内通知。"""

    def __init__(
        self,
        question_repository: QuestionRepository,
        answer_repository: AnswerRepository,
        notification_writer: NotificationWriter | None = None,
    ) -> None:
        self._question_repository = question_repository
        self._answer_repository = answer_repository
        self._notification_writer = notification_writer

    async def execute(self, command: VerifyAnswerCommand) -> Answer:
        question, answer = await _load_for_verification_change(
            self._question_repository,
            self._answer_repository,
            command.answer_id,
            "认证回答",
        )
        changed = answer.verify(command.actor_id)
        if changed:
            await self._answer_repository.update_verification(answer)
            if (
                self._notification_writer is not None
                and answer.author_id != command.actor_id
            ):
                await self._notification_writer.write(
                    recipient_id=answer.author_id,
                    type="answer_verified",
                    actor_id=command.actor_id,
                    target_type="answer",
                    target_id=answer.id,
                    source_event_id=uuid4(),
                    question_id=question.id,
                )
        return answer


class UnverifyAnswerUseCase:
    """取消认证回答：幂等清空认证状态，不发送通知、不触发声誉变动。"""

    def __init__(
        self,
        question_repository: QuestionRepository,
        answer_repository: AnswerRepository,
    ) -> None:
        self._question_repository = question_repository
        self._answer_repository = answer_repository

    async def execute(self, command: UnverifyAnswerCommand) -> None:
        _, answer = await _load_for_verification_change(
            self._question_repository,
            self._answer_repository,
            command.answer_id,
            "取消认证回答",
        )
        changed = answer.unverify()
        if changed:
            await self._answer_repository.update_verification(answer)
