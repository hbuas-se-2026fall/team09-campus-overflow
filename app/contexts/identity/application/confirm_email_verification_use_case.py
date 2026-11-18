"""确认邮箱验证码用例（F10）。"""

from __future__ import annotations

from app.contexts.identity.application.commands import ConfirmEmailVerificationCommand
from app.contexts.identity.application.ports import (
    EMAIL_VERIFY_MAX_ATTEMPTS,
    EmailVerificationStore,
    VerificationResult,
)
from app.contexts.identity.domain.errors import (
    InvalidCredentialsError,
    InvalidVerificationCodeError,
)
from app.contexts.identity.domain.repository import UserRepository
from app.contexts.identity.domain.value_objects import VerificationCode


class ConfirmEmailVerificationUseCase:
    """F10 D6 方案 A：主表行锁 + 先 verify 再 mark_email_verified，不提前删码（靠 TTL）。"""

    def __init__(
        self,
        users: UserRepository,
        store: EmailVerificationStore,
    ) -> None:
        self._users = users
        self._store = store

    async def execute(self, command: ConfirmEmailVerificationCommand) -> None:
        code = VerificationCode(command.code).value
        user = await self._users.get_by_id(command.user_id, for_update=True)
        if user is None:
            raise InvalidCredentialsError("用户不存在")
        if user.email_verified:
            return

        result = await self._store.verify(
            user.id, code, max_attempts=EMAIL_VERIFY_MAX_ATTEMPTS
        )
        if result is not VerificationResult.OK:
            raise InvalidVerificationCodeError("验证码无效或已过期")

        await self._users.mark_email_verified(user.id)
