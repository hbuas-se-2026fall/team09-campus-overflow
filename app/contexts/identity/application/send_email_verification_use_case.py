"""发送邮箱验证码用例（F10）。"""

from __future__ import annotations

import secrets

from app.contexts.identity.application.commands import SendEmailVerificationCommand
from app.contexts.identity.application.ports import (
    EMAIL_VERIFY_CODE_TTL_SECONDS,
    EMAIL_VERIFY_COOLDOWN_SECONDS,
    EmailVerificationStore,
    VerificationCodeSender,
)
from app.contexts.identity.domain.errors import (
    EmailAlreadyVerifiedError,
    InvalidCredentialsError,
)
from app.contexts.identity.domain.repository import UserRepository


class SendEmailVerificationUseCase:
    """生成 6 位安全随机码并发送；发信失败按 send_token 原子回滚冷却与验证码。"""

    def __init__(
        self,
        users: UserRepository,
        store: EmailVerificationStore,
        sender: VerificationCodeSender,
    ) -> None:
        self._users = users
        self._store = store
        self._sender = sender

    async def execute(self, command: SendEmailVerificationCommand) -> None:
        user = await self._users.get_by_id(command.user_id)
        if user is None:
            raise InvalidCredentialsError("用户不存在")
        if user.email_verified:
            raise EmailAlreadyVerifiedError("邮箱已完成验证")

        code = f"{secrets.randbelow(1_000_000):06d}"
        send_token = await self._store.prepare_send(
            user.id,
            code,
            cooldown_seconds=EMAIL_VERIFY_COOLDOWN_SECONDS,
            code_ttl_seconds=EMAIL_VERIFY_CODE_TTL_SECONDS,
        )
        try:
            await self._sender.send(user.email.value, code)
        except Exception:
            await self._store.rollback_send(user.id, send_token)
            raise
