"""公开个人主页只读用例（F11）：最小披露，不读敏感列。"""

from __future__ import annotations

from uuid import UUID

from app.contexts.identity.application.ports import (
    PublicUserProfile,
    PublicUserProfileReader,
)


class GetPublicUserProfileUseCase:
    def __init__(self, reader: PublicUserProfileReader) -> None:
        self._reader = reader

    async def execute(self, user_id: UUID) -> PublicUserProfile | None:
        return await self._reader.get_public_profile(user_id)
