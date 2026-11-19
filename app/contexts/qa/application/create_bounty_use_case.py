"""发起悬赏用例（F07）：问题必须存在且未关闭；教师身份由路由校验。"""

from __future__ import annotations

from app.contexts.qa.application.bounty_service import BountyService
from app.contexts.qa.application.commands import CreateBountyCommand
from app.contexts.qa.domain.bounty import Bounty
from app.contexts.qa.domain.errors import (
    AnswerAlreadyAcceptedError,
    QuestionNotFoundError,
)
from app.contexts.qa.domain.repository import QuestionRepository


class CreateBountyUseCase:
    def __init__(
        self, question_repository: QuestionRepository, service: BountyService
    ) -> None:
        self._questions = question_repository
        self._service = service

    async def execute(self, command: CreateBountyCommand) -> Bounty:
        question = await self._questions.get_by_id(
            command.question_id, for_update=True
        )
        if question is None:
            raise QuestionNotFoundError("问题不存在")
        question.ensure_open("发起悬赏")
        if question.accepted_answer_id is not None:
            raise AnswerAlreadyAcceptedError("该问题已有采纳答案，不可发起悬赏")
        return await self._service.create(
            command.question_id, command.teacher_id, command.amount
        )
