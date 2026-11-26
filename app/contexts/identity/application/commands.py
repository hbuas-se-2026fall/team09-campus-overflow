from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.contexts.identity.domain.user import Role
from app.shared.sentinel import UNSET, UnsetType


@dataclass(frozen=True, slots=True)
class RegisterCommand:
    """注册用例的输入命令。"""

    role: str
    email: str
    password: str
    student_id: str | None = None
    staff_id: str | None = None


@dataclass(frozen=True, slots=True)
class LoginCommand:
    """登录用例的输入命令。"""

    identifier: str
    password: str


@dataclass(frozen=True, slots=True)
class RefreshTokenCommand:
    """刷新用例的输入命令（US-L02 轮换）。"""

    refresh_token: str


@dataclass(frozen=True, slots=True)
class LogoutCommand:
    """登出用例的输入命令（US-L03 吊销，幂等）。"""

    refresh_token: str


@dataclass(frozen=True, slots=True)
class UpdateProfileCommand:
    """更新校园资料命令（F10）：UNSET 表示未传，None 表示显式清空。"""

    user_id: UUID
    nickname: str | None | UnsetType = UNSET
    college: str | None | UnsetType = UNSET
    class_name: str | None | UnsetType = UNSET


@dataclass(frozen=True, slots=True)
class SendEmailVerificationCommand:
    """发送邮箱验证码命令（F10）。"""

    user_id: UUID


@dataclass(frozen=True, slots=True)
class ConfirmEmailVerificationCommand:
    """确认邮箱验证码命令（F10）。"""

    user_id: UUID
    code: str


@dataclass(frozen=True, slots=True)
class UpdateUserRoleCommand:
    """管理员变更用户角色命令（F15）。"""

    actor_id: UUID
    target_user_id: UUID
    new_role: Role
