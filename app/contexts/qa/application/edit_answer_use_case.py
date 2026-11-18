"""编辑回答用例（US-A02 / F12）：仅回答者本人且所属问题未关闭。"""

from __future__ import annotations

from app.contexts.qa.application.commands import EditAnswerCommand
from app.contexts.qa.domain.answer import Answer
from app.contexts.qa.domain.errors import (
    AnswerNotFoundError,
    NotAnswerAuthorError,
    QuestionNotFoundError,
)
from app.contexts.qa.domain.repository import AnswerRepository, QuestionRepository


class EditAnswerUseCase:
    """编辑回答编排：
    1. 回答不存在 → AnswerNotFoundError（404）
    2. 非回答者本人 → NotAnswerAuthorError（403）
    3. 同事务对所属问题加行锁（for_update=True）并检查 open 态，已关闭 → QuestionClosedError（409）
    4. 领域值对象校验正文（DomainValidationError → 422）并调 update_body（不触碰 is_accepted）
    """

    def __init__(
        self,
        question_repository: QuestionRepository,
        answer_repository: AnswerRepository,
    ) -> None:
        self._question_repository = question_repository
        self._answer_repository = answer_repository

    async def execute(self, command: EditAnswerCommand) -> Answer:
        answer = await self._answer_repository.get_by_id(command.answer_id)
        if answer is None:
            raise AnswerNotFoundError("回答不存在")
        if answer.author_id != command.actor_id:
            raise NotAnswerAuthorError("仅回答者可编辑回答")
        question = await self._question_repository.get_by_id(
            answer.question_id, for_update=True
        )
        if question is None:
            raise QuestionNotFoundError("问题不存在")
        question.ensure_open("编辑回答")
        answer.edit_body(body_value=command.body)
        await self._answer_repository.update_body(answer)
        return answer
