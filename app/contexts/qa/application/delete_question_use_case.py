"""软删除问题用例（F13，D1–D3/D7）：仅提问者；已采纳 409；联动退还开放悬赏。"""

from __future__ import annotations

from app.contexts.qa.application.bounty_service import BountyService
from app.contexts.qa.application.commands import DeleteQuestionCommand
from app.contexts.qa.domain.errors import NotQuestionAuthorError, QuestionNotFoundError
from app.contexts.qa.domain.repository import QuestionRepository


class DeleteQuestionUseCase:
    """软删除问题编排：
    1. 带行锁读取（含已删行）：不存在 → 404；
    2. 已删态：作者重复删除幂等 204（不二次退款），非作者 404（不泄露存在性）；
    3. 鉴权优先于状态冲突：非作者 → 403；
    4. 领域 soft_delete：已有采纳答案 → 409；已关闭允许删除；
    5. 仓储条件 soft_delete：返回 True 时若注入 BountyService 则全额退还开放悬赏。
    """

    def __init__(
        self,
        question_repository: QuestionRepository,
        bounty_service: BountyService | None = None,
    ) -> None:
        self._question_repository = question_repository
        self._bounty_service = bounty_service

    async def execute(self, command: DeleteQuestionCommand) -> None:
        question = await self._question_repository.get_by_id(
            command.question_id, for_update=True, include_deleted=True
        )
        if question is None:
            raise QuestionNotFoundError("问题不存在")
        if question.is_deleted:
            if question.author_id == command.actor_id:
                return
            raise QuestionNotFoundError("问题不存在")
        if question.author_id != command.actor_id:
            raise NotQuestionAuthorError("仅提问者可删除问题")
        question.soft_delete()
        assert question.deleted_at is not None
        deleted = await self._question_repository.soft_delete(
            question.id, question.deleted_at
        )
        if deleted and self._bounty_service is not None:
            await self._bounty_service.refund_on_delete(question.id)
