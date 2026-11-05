from __future__ import annotations

from dataclasses import dataclass


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
