"""公开个人主页用例单元测试（不连库）。"""

from __future__ import annotations

from uuid import UUID

from app.contexts.identity.application.get_public_profile_use_case import (
    GetPublicUserProfileUseCase,
)
from app.contexts.identity.application.ports import PublicUserProfile


class _FakeProfileReader:
    def __init__(self, profiles: dict[UUID, PublicUserProfile]) -> None:
        self._profiles = profiles

    async def get_public_profile(self, user_id: UUID) -> PublicUserProfile | None:
        return self._profiles.get(user_id)


async def test_get_public_profile_returns_profile_when_exists() -> None:
    uid = UUID("11111111-1111-1111-1111-111111111111")
    profile = PublicUserProfile(
        user_id=uid,
        role="student",
        display_name="小张",
        nickname="小张",
        college="计算机学院",
        class_name="软工2401",
    )
    use_case = GetPublicUserProfileUseCase(_FakeProfileReader({uid: profile}))
    assert await use_case.execute(uid) == profile


async def test_get_public_profile_returns_none_when_missing() -> None:
    use_case = GetPublicUserProfileUseCase(_FakeProfileReader({}))
    assert await use_case.execute(UUID("22222222-2222-2222-2222-222222222222")) is None
