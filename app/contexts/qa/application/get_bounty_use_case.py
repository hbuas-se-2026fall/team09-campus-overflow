"""查询悬赏用例（F07）：仅返回进行中的悬赏，无则 None。"""

from __future__ import annotations

from uuid import UUID

from app.contexts.qa.domain.bounty import Bounty
from app.contexts.qa.domain.repository import BountyRepository


class GetBountyUseCase:
    def __init__(self, repository: BountyRepository) -> None:
        self._repository = repository

    async def execute(self, question_id: UUID) -> Bounty | None:
        return await self._repository.get_active(question_id)
