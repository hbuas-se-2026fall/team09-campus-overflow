"""刷新/登出用例单测：fake 仓储/令牌服务/存储，不连库（进 CI）。

覆盖轮换原子性：成功签发、旧 jti 复放 401、新 refresh 可继续轮换、
DB 读失败不消耗令牌（503 可重试语义）、用户不存在/消耗失败/解码失败、logout 幂等。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.contexts.identity.application.commands import LogoutCommand, RefreshTokenCommand
from app.contexts.identity.application.logout_use_case import LogoutUseCase
from app.contexts.identity.application.ports import REFRESH_TOKEN_TTL
from app.contexts.identity.application.refresh_token_use_case import RefreshTokenUseCase
from app.contexts.identity.domain.errors import (
    InvalidRefreshTokenError,
    UserNotFoundError,
)
from app.contexts.identity.domain.user import Role, User
from app.contexts.identity.domain.value_objects import Email, PasswordHash

_OLD_TOKEN = "old-refresh-token"


def _user() -> User:
    return User(
        id=uuid4(),
        role="student",
        email=Email("student@example.edu"),
        password_hash=PasswordHash("$2b$12$abcdefghijklmnopqrstuv"),
        student_id=None,
        staff_id=None,
        created_at=datetime.now(UTC),
    )


class FakeUserRepository:
    def __init__(self, user: User | None) -> None:
        self._user = user
        self.reads = 0

    async def get_by_id(self, user_id: UUID, *, for_update: bool = False) -> User | None:
        self.reads += 1
        return self._user

    async def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        role: Role | None = None,
    ) -> tuple[list[User], int]:
        if self._user is None or (role is not None and self._user.role != role):
            return [], 0
        return ([self._user], 1) if page == 1 and page_size >= 1 else ([], 1)

    async def update_role(self, user_id: UUID, new_role: Role) -> User:
        if self._user is None or self._user.id != user_id:
            raise UserNotFoundError("用户不存在")
        self._user.change_role(new_role)
        return self._user


class FailingUserRepository:
    """模拟 DB 不可达（用例须在消耗令牌之前失败）。"""

    def __init__(self, error: Exception) -> None:
        self._error = error

    async def get_by_id(self, user_id: UUID, *, for_update: bool = False) -> User | None:
        raise self._error


class FakeTokenService:
    def __init__(self) -> None:
        self._issued: dict[str, tuple[UUID, UUID]] = {}

    def register(self, token: str, user_id: UUID, jti: UUID) -> None:
        self._issued[token] = (user_id, jti)

    def decode_refresh(self, token: str) -> tuple[UUID, UUID] | None:
        return self._issued.get(token)

    def issue_access(self, user: User) -> str:
        return f"access-{user.id}"

    def issue_refresh(self, user: User) -> tuple[str, UUID]:
        jti = uuid4()
        token = f"refresh-{jti}"
        self._issued[token] = (user.id, jti)
        return token, jti


class FakeRefreshStore:
    def __init__(self) -> None:
        self.tokens: dict[UUID, UUID] = {}
        self.consumed: list[UUID] = []
        self.saved: list[tuple[UUID, UUID, timedelta]] = []
        self.revoked: list[UUID] = []

    async def save(self, jti: UUID, user_id: UUID, ttl: timedelta) -> None:
        self.tokens[jti] = user_id
        self.saved.append((jti, user_id, ttl))

    async def consume(self, jti: UUID) -> UUID | None:
        self.consumed.append(jti)
        return self.tokens.pop(jti, None)

    async def revoke(self, jti: UUID) -> None:
        self.revoked.append(jti)
        self.tokens.pop(jti, None)


def _arrange() -> tuple[User, FakeTokenService, FakeRefreshStore, UUID]:
    user = _user()
    tokens = FakeTokenService()
    store = FakeRefreshStore()
    old_jti = uuid4()
    tokens.register(_OLD_TOKEN, user.id, old_jti)
    store.tokens[old_jti] = user.id
    return user, tokens, store, old_jti


async def test_refresh_rotates_and_returns_new_pair() -> None:
    user, tokens, store, old_jti = _arrange()
    use_case = RefreshTokenUseCase(FakeUserRepository(user), tokens, store)

    pair = await use_case.execute(RefreshTokenCommand(refresh_token=_OLD_TOKEN))

    assert pair.access_token == f"access-{user.id}"
    assert pair.refresh_token == f"refresh-{pair.refresh_jti}"
    assert store.consumed == [old_jti]
    assert store.saved == [(pair.refresh_jti, user.id, REFRESH_TOKEN_TTL)]


async def test_old_refresh_replay_is_rejected_after_rotation() -> None:
    user, tokens, store, _ = _arrange()
    use_case = RefreshTokenUseCase(FakeUserRepository(user), tokens, store)

    await use_case.execute(RefreshTokenCommand(refresh_token=_OLD_TOKEN))

    with pytest.raises(InvalidRefreshTokenError, match="已失效"):
        await use_case.execute(RefreshTokenCommand(refresh_token=_OLD_TOKEN))


async def test_new_refresh_token_can_rotate_again() -> None:
    user, tokens, store, _ = _arrange()
    use_case = RefreshTokenUseCase(FakeUserRepository(user), tokens, store)

    first = await use_case.execute(RefreshTokenCommand(refresh_token=_OLD_TOKEN))
    second = await use_case.execute(
        RefreshTokenCommand(refresh_token=first.refresh_token)
    )

    assert second.refresh_jti != first.refresh_jti


async def test_db_failure_does_not_consume_token() -> None:
    _, tokens, store, _ = _arrange()
    use_case = RefreshTokenUseCase(
        FailingUserRepository(ConnectionError("db down")), tokens, store
    )

    with pytest.raises(ConnectionError):
        await use_case.execute(RefreshTokenCommand(refresh_token=_OLD_TOKEN))

    assert store.consumed == []


async def test_unknown_user_is_rejected() -> None:
    _, tokens, store, _ = _arrange()
    use_case = RefreshTokenUseCase(FakeUserRepository(None), tokens, store)

    with pytest.raises(InvalidRefreshTokenError, match="用户不存在"):
        await use_case.execute(RefreshTokenCommand(refresh_token=_OLD_TOKEN))

    assert store.consumed == []


async def test_unknown_jti_is_rejected() -> None:
    user, tokens, store, _ = _arrange()
    store.tokens.clear()  # 令牌有效但已过期/被吊销
    use_case = RefreshTokenUseCase(FakeUserRepository(user), tokens, store)

    with pytest.raises(InvalidRefreshTokenError, match="已失效"):
        await use_case.execute(RefreshTokenCommand(refresh_token=_OLD_TOKEN))


async def test_jti_owner_mismatch_is_rejected() -> None:
    user, tokens, store, old_jti = _arrange()
    store.tokens[old_jti] = uuid4()  # 存储侧归属与令牌 sub 不一致（伪造/污染）
    use_case = RefreshTokenUseCase(FakeUserRepository(user), tokens, store)

    with pytest.raises(InvalidRefreshTokenError, match="已失效"):
        await use_case.execute(RefreshTokenCommand(refresh_token=_OLD_TOKEN))


async def test_invalid_token_is_rejected() -> None:
    user, tokens, store, _ = _arrange()
    use_case = RefreshTokenUseCase(FakeUserRepository(user), tokens, store)

    with pytest.raises(InvalidRefreshTokenError, match="无效或已过期"):
        await use_case.execute(RefreshTokenCommand(refresh_token="garbage"))

    assert store.consumed == []


async def test_logout_revokes_jti() -> None:
    _, tokens, store, old_jti = _arrange()
    use_case = LogoutUseCase(tokens, store)

    await use_case.execute(LogoutCommand(refresh_token=_OLD_TOKEN))

    assert store.revoked == [old_jti]


async def test_logout_with_invalid_token_is_noop() -> None:
    _, tokens, store, _ = _arrange()
    use_case = LogoutUseCase(tokens, store)

    await use_case.execute(LogoutCommand(refresh_token="garbage"))

    assert store.revoked == []
