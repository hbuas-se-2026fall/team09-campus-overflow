"""采纳用例：提问者采纳最佳答案（US-V03，跨聚合编排 + 单事务双写）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from app.contexts.qa.application.bounty_service import BountyService
from app.contexts.qa.application.commands import AcceptAnswerCommand
from app.contexts.qa.application.ports import NotificationWriter
from app.contexts.qa.domain.answer import Answer, AnswerAccepted
from app.contexts.qa.domain.errors import (
    AnswerAlreadyAcceptedError,
    AnswerNotFoundError,
    NotQuestionAuthorError,
    QuestionNotFoundError,
)
from app.contexts.qa.domain.repository import AnswerRepository, QuestionRepository


@dataclass(frozen=True, slots=True)
class AcceptOutcome:
    """采纳结果：更新后的回答 + AnswerAccepted 事件（分支 4 声誉消费方留位）。"""

    answer: Answer
    event: AnswerAccepted


class AcceptAnswerUseCase:
    """采纳编排（计划 v3 分支 2；迭代 5 追加关闭态拦截）：

    1. 回答不存在 → AnswerNotFoundError（404）
    2. 仅提问者 → NotQuestionAuthorError（403，1.3 功能域 8）
    3. 已关闭问题不可采纳 → QuestionClosedError（409，2026-09-29 全冻结裁定）
    4. 一题一采纳：问题已有 accepted_answer_id → AnswerAlreadyAcceptedError（409，
       重复采纳含"再次采纳同一答案"一律拒绝——计划 L73 定稿）
    5. 跨聚合双写 Answer.is_accepted + Question.accepted_answer_id：
       同一 AsyncSession 事务内完成，任一侧失败整体回滚（计划 L74 事务边界）；
       请求结束由 get_session 统一 commit。
    6. 成功发 AnswerAccepted（用例代发，与 VoteCast 同模式）。
    7. F04 通知答主；F07/D13 同事务结算进行中的悬赏。
    """

    def __init__(
        self,
        question_repository: QuestionRepository,
        answer_repository: AnswerRepository,
        notification_writer: NotificationWriter | None = None,
        bounty_service: BountyService | None = None,
    ) -> None:
        self._question_repository = question_repository
        self._answer_repository = answer_repository
        self._notification_writer = notification_writer
        self._bounty_service = bounty_service

    async def execute(self, command: AcceptAnswerCommand) -> AcceptOutcome:
        answer = await self._answer_repository.get_by_id(command.answer_id)
        if answer is None:
            raise AnswerNotFoundError("回答不存在")
        question = await self._question_repository.get_by_id(
            answer.question_id, for_update=True
        )
        if question is None:
            raise QuestionNotFoundError("问题不存在")
        # 拿到父问题锁后重读 Answer，闭环并发软删回答窗口（F13 D4）
        answer = await self._answer_repository.get_by_id(command.answer_id)
        if answer is None:
            raise AnswerNotFoundError("回答不存在")
        if question.author_id != command.actor_id:
            raise NotQuestionAuthorError("仅提问者可采纳答案")
        question.ensure_open("采纳")
        if question.accepted_answer_id is not None:
            raise AnswerAlreadyAcceptedError("该问题已有采纳答案")

        answer.accept()
        question.mark_accepted(answer.id)
        await self._answer_repository.update(answer)
        await self._question_repository.update(question)

        event = AnswerAccepted(
            event_id=uuid4(),  # 幂等键（v3.1 裁定 1a）：采纳事务内生成一次
            answer_id=answer.id,
            question_id=question.id,
            answer_author_id=answer.author_id,
            accepted_by=command.actor_id,
            occurred_at=datetime.now(UTC),
        )
        if (
            self._notification_writer is not None
            and answer.author_id != command.actor_id
        ):
            await self._notification_writer.write(
                recipient_id=answer.author_id,
                type="answer_accepted",
                actor_id=command.actor_id,
                target_type="answer",
                target_id=answer.id,
                source_event_id=event.event_id,
                question_id=question.id,
            )
        if self._bounty_service is not None:
            # F07/D13：采纳同事务结算进行中的悬赏（条件更新保证只结算一次）
            await self._bounty_service.settle_on_accept(question.id, answer.author_id)
        return AcceptOutcome(answer=answer, event=event)
