"""软删除回答用例（F13，D1–D4/D7）：仅回答者；父问题已删统一 404；已采纳 409。"""

from __future__ import annotations

from app.contexts.qa.application.commands import DeleteAnswerCommand
from app.contexts.qa.domain.errors import (
    AnswerNotFoundError,
    NotAnswerAuthorError,
    QuestionNotFoundError,
)
from app.contexts.qa.domain.repository import AnswerRepository, QuestionRepository


class DeleteAnswerUseCase:
    """软删除回答编排（统一锁序“无锁读 Answer → 锁父 Question → 重读 Answer”）：
    1. 初步定位回答（含已删）：不存在 → 404；
    2. 锁父问题（含已删）：父问题不存在或已删 → 404（优先于作者检查，避免泄露）；
    3. 锁后重读回答（含已删）：闭环并发窗口；
    4. 已删态（父问题活跃）：作者重复删除幂等 204，非作者 404；
    5. 鉴权优先于状态冲突：非作者 → 403；
    6. 领域 soft_delete：已采纳 → 409；已关闭问题下允许删除回答（内容回收例外）；
    7. 仓储条件 soft_delete 落库。
    """

    def __init__(
        self,
        question_repository: QuestionRepository,
        answer_repository: AnswerRepository,
    ) -> None:
        self._question_repository = question_repository
        self._answer_repository = answer_repository

    async def execute(self, command: DeleteAnswerCommand) -> None:
        answer = await self._answer_repository.get_by_id(
            command.answer_id, include_deleted=True
        )
        if answer is None:
            raise AnswerNotFoundError("回答不存在")
        parent = await self._question_repository.get_by_id(
            answer.question_id, for_update=True, include_deleted=True
        )
        if parent is None or parent.is_deleted:
            raise QuestionNotFoundError("问题不存在")
        answer = await self._answer_repository.get_by_id(
            command.answer_id, include_deleted=True
        )
        if answer is None:
            raise AnswerNotFoundError("回答不存在")
        if answer.is_deleted:
            if answer.author_id == command.actor_id:
                return
            raise AnswerNotFoundError("回答不存在")
        if answer.author_id != command.actor_id:
            raise NotAnswerAuthorError("仅回答者可删除回答")
        answer.soft_delete()
        assert answer.deleted_at is not None
        await self._answer_repository.soft_delete(answer.id, answer.deleted_at)
