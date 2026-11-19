from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from app.contexts.identity.domain.user import User

# 令牌 TTL：签发与存储共用同一常量，避免两处漂移
ACCESS_TOKEN_TTL = timedelta(minutes=15)
REFRESH_TOKEN_TTL = timedelta(days=7)

# 登录失败锁定参数（US-L04，2026-09-29 裁定：全 identifier 统一计数，5 次/15 分钟窗口）
LOGIN_FAILURE_THRESHOLD = 5
LOGIN_LOCKOUT_WINDOW = timedelta(minutes=15)

# F10 邮箱验证码参数：60s 冷却 / 15min 有效 / 5 次错码作废
EMAIL_VERIFY_COOLDOWN_SECONDS = 60
EMAIL_VERIFY_CODE_TTL_SECONDS = 900
EMAIL_VERIFY_MAX_ATTEMPTS = 5


class PasswordHasher(Protocol):
    """密码哈希端口：application 定义，infrastructure 提供 bcrypt 实现。"""

    async def hash(self, plain: str) -> str:
        """将明文密码转为 bcrypt 哈希。"""
        ...

    async def verify(self, plain: str, hashed: str) -> bool:
        """校验明文密码与哈希是否匹配。"""
        ...


@dataclass(frozen=True, slots=True)
class TokenPair:
    """签发出的令牌对。"""

    access_token: str
    refresh_token: str
    refresh_jti: UUID


class TokenService(Protocol):
    """JWT 签发与校验端口：JWT 细节不进 application。"""

    def issue_access(self, user: User) -> str:
        """签发 Access 令牌（typ=access，TTL 15min）。"""
        ...

    def issue_refresh(self, user: User) -> tuple[str, UUID]:
        """签发 Refresh 令牌（typ=refresh + jti，TTL 7d），返回 (token, jti)。"""
        ...

    def verify_access(self, token: str) -> UUID | None:
        """校验 Access 令牌：签名/过期/typ 全通过返回 user_id，否则 None。"""
        ...

    def decode_refresh(self, token: str) -> tuple[UUID, UUID] | None:
        """解码 Refresh 令牌：返回 (user_id, jti)，无效返回 None。"""
        ...


class RefreshTokenStore(Protocol):
    """Refresh 令牌存储端口：Redis 实现，支持原子消耗（防并发重放）。"""

    async def save(self, jti: UUID, user_id: UUID, ttl: timedelta) -> None:
        """保存 refresh:{jti} → user_id，TTL 后自动过期。"""
        ...

    async def consume(self, jti: UUID) -> UUID | None:
        """原子"校验并消耗"：存在则删除并返回 user_id，不存在返回 None（GETDEL 语义）。"""
        ...

    async def revoke(self, jti: UUID) -> None:
        """吊销：删除 refresh:{jti}，幂等。"""
        ...


class LoginAttemptGuard(Protocol):
    """登录失败计数/锁定守卫端口（US-L04）。

    锁定时瞬态运维状态，非领域不变式（aggregates.md User 不变式未列它）——
    用 Redis 计数器实现，不动 User 聚合、无迁移（2026-09-29 裁定）。
    """

    async def check_locked(self, identifier: str) -> bool:
        """是否已锁定（失败次数 ≥ 阈值）。"""
        ...

    async def record_failure(self, identifier: str) -> None:
        """记录一次登录失败（计数 + 刷新窗口 TTL）。"""
        ...

    async def clear(self, identifier: str) -> None:
        """登录成功清零失败计数（幂等）。"""
        ...


class VerificationResult(StrEnum):
    """邮箱验证码校验结果（F10）。"""

    OK = "ok"
    INVALID = "invalid"
    EXPIRED = "expired"
    TOO_MANY = "too_many"


class EmailVerificationStore(Protocol):
    """邮箱验证码存储端口（F10）：只校验与计数，不在事务内提前删码（靠 900s TTL）。"""

    async def prepare_send(
        self,
        user_id: UUID,
        code: str,
        *,
        cooldown_seconds: int,
        code_ttl_seconds: int,
    ) -> str:
        """原子检查冷却并写入冷却态与验证码哈希，返回本次 send_token。"""
        ...

    async def rollback_send(self, user_id: UUID, send_token: str) -> None:
        """发信失败时仅当 token 匹配才同时回滚冷却键与验证码键。"""
        ...

    async def verify(
        self,
        user_id: UUID,
        code: str,
        *,
        max_attempts: int,
    ) -> VerificationResult:
        """原子比对验证码并累加错码次数（满 max_attempts 作废删码；成功不删码）。"""
        ...


class VerificationCodeSender(Protocol):
    """邮箱验证码发送端口（F10）。"""

    async def send(self, email: str, code: str) -> None:
        """发送 6 位验证码至目标邮箱；发送故障须转为 EmailVerificationUnavailableError。"""
        ...


UNKNOWN_USER_DISPLAY_NAME = "未知用户"


@dataclass(frozen=True, slots=True)
class UserSummary:
    """F11 已发布语言：跨上下文只读用户公开摘要（不含任何隐私字段）。"""

    user_id: UUID
    display_name: str
    role: str


def pick_summary_display_name(
    summaries: Mapping[UUID, UserSummary], user_id: UUID
) -> str:
    """F11 已发布语言：从批量摘要中取展示名，缺失用户统一安全回退。"""
    summary = summaries.get(user_id)
    return summary.display_name if summary is not None else UNKNOWN_USER_DISPLAY_NAME


@dataclass(frozen=True, slots=True)
class PublicUserProfile:
    """F11 公开个人主页读模型（最小披露：不含邮箱/学工号/验证态/密码哈希）。"""

    user_id: UUID
    role: str
    display_name: str
    nickname: str | None
    college: str | None
    class_name: str | None


class UserSummaryReader(Protocol):
    """F11 公开展示名批量读取端口（供下游 interfaces 层回填）。"""

    async def get_summaries(self, user_ids: Iterable[UUID]) -> dict[UUID, UserSummary]:
        """按 user_ids 批量查询公开摘要；空集合零 SQL，缺失用户不入字典、不报错。"""
        ...


class PublicUserProfileReader(Protocol):
    """F11 公开个人主页读取端口（仅投影公开列）。"""

    async def get_public_profile(self, user_id: UUID) -> PublicUserProfile | None:
        """按 user_id 查询公开个人主页；不存在返回 None。"""
        ...
