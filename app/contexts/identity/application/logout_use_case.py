"""登出用例（US-L03）：吊销 Refresh 令牌，无效/已吊销令牌幂等成功（不暴露状态）。"""

from __future__ import annotations

from app.contexts.identity.application.commands import LogoutCommand
from app.contexts.identity.application.ports import RefreshTokenStore, TokenService


class LogoutUseCase:
    """吊销当前 Refresh 的 jti；解码失败直接静默成功（幂等 204 语义）。"""

    def __init__(self, token_service: TokenService, refresh_store: RefreshTokenStore) -> None:
        self._token_service = token_service
        self._refresh_store = refresh_store

    async def execute(self, command: LogoutCommand) -> None:
        decoded = self._token_service.decode_refresh(command.refresh_token)
        if decoded is None:
            return
        _, jti = decoded
        await self._refresh_store.revoke(jti)
