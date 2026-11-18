"""邮箱验证码 Redis 存储适配器（F10）。

设计要点：
- Redis 中只存 HMAC-SHA256 摘要（使用独立 hmac_secret），绝不存明文 6 位码；
- 冷却键 `email_verify:cd:{user_id}` 与验证码键 `email_verify:code:{user_id}` 共同绑定本次
  `send_token`，发信失败通过 Lua compare-and-delete 仅回滚自己，绝不误删并发新码；
- verify 仅核对 HMAC 与累加错码次数（满 max_attempts 作废删码），成功不删码（D6 方案 1）；
- Redis / 连接异常统一转为 EmailVerificationUnavailableError → 503。
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from redis.exceptions import RedisError

from app.contexts.identity.application.ports import VerificationResult
from app.contexts.identity.domain.errors import (
    EmailVerificationUnavailableError,
    VerificationCooldownError,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_CD_PREFIX = "email_verify:cd:"
_CODE_PREFIX = "email_verify:code:"

_PREPARE_SEND_LUA = """
if redis.call('EXISTS', KEYS[1]) == 1 then
    return 0
end
redis.call('SET', KEYS[1], ARGV[1], 'EX', tonumber(ARGV[2]))
redis.call('HSET', KEYS[2], 'hash', ARGV[3], 'attempts', '0', 'token', ARGV[1])
redis.call('EXPIRE', KEYS[2], tonumber(ARGV[4]))
return 1
"""

_ROLLBACK_SEND_LUA = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
    redis.call('DEL', KEYS[1])
end
if redis.call('HGET', KEYS[2], 'token') == ARGV[1] then
    redis.call('DEL', KEYS[2])
end
return 1
"""

_VERIFY_LUA = """
local stored = redis.call('HGET', KEYS[1], 'hash')
if not stored then
    return 'expired'
end
if stored == ARGV[1] then
    return 'ok'
end
local attempts = redis.call('HINCRBY', KEYS[1], 'attempts', 1)
if attempts >= tonumber(ARGV[2]) then
    redis.call('DEL', KEYS[1])
    return 'too_many'
end
return 'invalid'
"""


def _decode_lua_str(raw: Any) -> str:
    if isinstance(raw, bytes):
        return raw.decode("utf-8")
    return str(raw)


class RedisEmailVerificationStore:
    """EmailVerificationStore 端口的 Redis + Lua 原子实现。"""

    def __init__(
        self,
        hmac_secret: str,
        client_factory: Callable[[], Redis],
    ) -> None:
        self._secret = hmac_secret.encode("utf-8")
        self._client_factory = client_factory

    def _hash_code(self, user_id: UUID, code: str) -> str:
        msg = f"{user_id}:{code}".encode()
        return hmac.new(self._secret, msg, hashlib.sha256).hexdigest()

    async def prepare_send(
        self,
        user_id: UUID,
        code: str,
        *,
        cooldown_seconds: int,
        code_ttl_seconds: int,
    ) -> str:
        send_token = uuid4().hex
        cd_key = f"{_CD_PREFIX}{user_id}"
        code_key = f"{_CODE_PREFIX}{user_id}"
        code_hash = self._hash_code(user_id, code)
        try:
            res = await self._client_factory().eval(  # type: ignore[misc]
                _PREPARE_SEND_LUA,
                2,
                cd_key,
                code_key,
                send_token,
                str(cooldown_seconds),
                code_hash,
                str(code_ttl_seconds),
            )
        except (RedisError, OSError, ValueError, TypeError) as exc:
            raise EmailVerificationUnavailableError("邮箱验证服务暂时不可用，请稍后重试") from exc
        if int(res) == 0:
            raise VerificationCooldownError("发送过于频繁，请 60 秒后再试")
        return send_token

    async def rollback_send(self, user_id: UUID, send_token: str) -> None:
        cd_key = f"{_CD_PREFIX}{user_id}"
        code_key = f"{_CODE_PREFIX}{user_id}"
        try:
            await self._client_factory().eval(  # type: ignore[misc]
                _ROLLBACK_SEND_LUA,
                2,
                cd_key,
                code_key,
                send_token,
            )
        except (RedisError, OSError, ValueError, TypeError):
            logger.warning("邮箱验证码回滚失败（已忽略）: user_id=%s", user_id, exc_info=True)

    async def verify(
        self,
        user_id: UUID,
        code: str,
        *,
        max_attempts: int,
    ) -> VerificationResult:
        code_key = f"{_CODE_PREFIX}{user_id}"
        code_hash = self._hash_code(user_id, code)
        try:
            raw = await self._client_factory().eval(  # type: ignore[misc]
                _VERIFY_LUA,
                1,
                code_key,
                code_hash,
                str(max_attempts),
            )
        except (RedisError, OSError, ValueError, TypeError) as exc:
            raise EmailVerificationUnavailableError("邮箱验证服务暂时不可用，请稍后重试") from exc
        return VerificationResult(_decode_lua_str(raw))
