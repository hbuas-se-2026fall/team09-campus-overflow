"""刷新令牌用例（US-L02 轮换）：解码 → 读用户 → 原子消耗 → 签发新对 → 存储新 jti。

顺序红线（第八路观察点 3）：**先读用户再消耗令牌**——DB 读失败返回 503 时
令牌未被 GETDEL 烧毁，客户端按契约重试可成功；先消耗再读会让 503 重试必然 401。
"""

from __future__ import annotations

from app.contexts.identity.application.commands import RefreshTokenCommand
from app.contexts.identity.application.ports import (
    REFRESH_TOKEN_TTL,
    RefreshTokenStore,
    TokenPair,
    TokenService,
)
from app.contexts.identity.domain.errors import InvalidRefreshTokenError
from app.contexts.identity.domain.repository import UserRepository


class RefreshTokenUseCase:
    """轮换刷新令牌：旧 jti 原子消耗（并发仅一次成功），新 jti 落存储。"""

    def __init__(
        self,
        repository: UserRepository,
        token_service: TokenService,
        refresh_store: RefreshTokenStore,
    ) -> None:
        self._repository = repository
        self._token_service = token_service
        self._refresh_store = refresh_store

    async def execute(self, command: RefreshTokenCommand) -> TokenPair:
        decoded = self._token_service.decode_refresh(command.refresh_token)
        if decoded is None:
            raise InvalidRefreshTokenError("刷新令牌无效或已过期")
        user_id, jti = decoded

        # 先读用户：DB 失败时不得消耗令牌（可重试语义）
        user = await self._repository.get_by_id(user_id)
        if user is None:
            raise InvalidRefreshTokenError("用户不存在")

        consumed = await self._refresh_store.consume(jti)
        if consumed is None or consumed != user_id:
            raise InvalidRefreshTokenError("刷新令牌已失效")

        access_token = self._token_service.issue_access(user)
        refresh_token, new_jti = self._token_service.issue_refresh(user)
        await self._refresh_store.save(new_jti, user.id, REFRESH_TOKEN_TTL)
        return TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            refresh_jti=new_jti,
        )
