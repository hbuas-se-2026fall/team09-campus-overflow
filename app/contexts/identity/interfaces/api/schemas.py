from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.shared.errors import DomainValidationError
from app.shared.text_validation import reject_unsafe_text


class RegisterRequest(BaseModel):
    """POST /api/v1/auth/register 请求体。"""

    model_config = ConfigDict(extra="forbid")

    role: Literal["student", "teacher"]
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=128)
    student_id: str | None = Field(default=None, max_length=32)
    staff_id: str | None = Field(default=None, max_length=32)

    @field_validator("email", "student_id", "staff_id")
    @classmethod
    def _reject_unsafe_chars(cls, value: str | None) -> str | None:
        # 注册用例先查重（SQL 参数）再构造值对象，NUL/代理字符必须在边界拦截，
        # 否则 asyncpg 报 CharacterNotInRepertoireError → 500
        if value is not None:
            reject_unsafe_text(value, field_name="注册信息")
        return value

    @model_validator(mode="after")
    def _identity_matches_role(self) -> RegisterRequest:
        if self.role == "student" and not self.student_id:
            raise DomainValidationError("学生注册必须提供 student_id")
        if self.role == "teacher" and not self.staff_id:
            raise DomainValidationError("教师注册必须提供 staff_id")
        return self


class RegisterResponse(BaseModel):
    """注册/当前用户响应：绝不包含密码任何形态。"""

    id: UUID
    role: str
    email: str
    student_id: str | None
    staff_id: str | None
    nickname: str | None = None
    college: str | None = None
    class_name: str | None = None
    email_verified: bool = False
    created_at: datetime


class UpdateProfileRequest(BaseModel):
    """PATCH /api/v1/auth/me/profile 请求体（F10）：空 body 422；显式 null 清空。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    nickname: str | None = Field(default=None, min_length=1, max_length=30)
    college: str | None = Field(default=None, min_length=1, max_length=64)
    class_name: str | None = Field(default=None, min_length=1, max_length=64)

    @field_validator("nickname", "college", "class_name")
    @classmethod
    def _reject_unsafe_chars(cls, value: str | None) -> str | None:
        if value is not None:
            reject_unsafe_text(value, field_name="个人资料")
        return value

    @model_validator(mode="after")
    def _require_any_field(self) -> UpdateProfileRequest:
        if not self.model_fields_set:
            raise DomainValidationError("至少提供一项资料字段")
        return self


class ConfirmEmailVerificationRequest(BaseModel):
    """POST /api/v1/auth/me/verify-email/confirm 请求体（F10）。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    code: str = Field(min_length=6, max_length=6)

    @field_validator("code")
    @classmethod
    def _reject_unsafe_chars(cls, value: str) -> str:
        reject_unsafe_text(value, field_name="验证码")
        return value


class LoginRequest(BaseModel):
    """POST /api/v1/auth/login 请求体：identifier 为学号或工号。"""

    model_config = ConfigDict(extra="forbid")

    identifier: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("identifier", "password")
    @classmethod
    def _reject_unsafe_chars(cls, value: str) -> str:
        # 只拒控制字符/代理字符，不碰格式：SQL 注入串等仍透传到用例返回 401
        reject_unsafe_text(value, field_name="登录信息")
        return value


class RefreshRequest(BaseModel):
    """POST /api/v1/auth/refresh 与 /logout 请求体。"""

    model_config = ConfigDict(extra="forbid")

    refresh_token: str = Field(min_length=1)


class TokenPairResponse(BaseModel):
    """登录/刷新成功返回的令牌对。"""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # Access 令牌有效秒数（15min = 900）
