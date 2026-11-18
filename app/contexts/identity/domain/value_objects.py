from __future__ import annotations

import re
from dataclasses import dataclass

from app.shared.errors import DomainValidationError
from app.shared.text_validation import reject_unsafe_text

_STUDENT_ID_PATTERN = re.compile(r"^\d{8,12}$")
_STAFF_ID_PATTERN = re.compile(r"^T\d{4,8}$")
_EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# 仅允许 ASCII 0–9，拒绝全角/Unicode 数字字符
_VERIFICATION_CODE_PATTERN = re.compile(r"^[0-9]{6}$")
_NICKNAME_MAX_LENGTH = 30
_CAMPUS_META_MAX_LENGTH = 64


def _normalize_profile_text(raw: str, *, field_name: str, max_length: int) -> str:
    reject_unsafe_text(raw, field_name=field_name)
    cleaned = raw.strip()
    if not cleaned:
        raise DomainValidationError(f"{field_name}不能为空")
    if len(cleaned) > max_length:
        raise DomainValidationError(f"{field_name}至多 {max_length} 个字符")
    return cleaned


@dataclass(frozen=True, slots=True)
class StudentId:
    """学号：8~12 位数字，全局唯一。"""

    value: str

    def __post_init__(self) -> None:
        reject_unsafe_text(self.value, field_name="学号")
        if not _STUDENT_ID_PATTERN.match(self.value):
            raise DomainValidationError(f"学号格式不合法：{self.value!r}（应为 8~12 位数字）")


@dataclass(frozen=True, slots=True)
class StaffId:
    """工号：T 开头 + 4~8 位数字，全局唯一。"""

    value: str

    def __post_init__(self) -> None:
        reject_unsafe_text(self.value, field_name="工号")
        if not _STAFF_ID_PATTERN.match(self.value):
            raise DomainValidationError(f"工号格式不合法：{self.value!r}（应为 T+4~8 位数字）")


@dataclass(frozen=True, slots=True)
class Email:
    """邮箱：基础格式校验，全局唯一。"""

    value: str

    def __post_init__(self) -> None:
        reject_unsafe_text(self.value, field_name="邮箱")
        if not _EMAIL_PATTERN.match(self.value):
            raise DomainValidationError(f"邮箱格式不合法：{self.value!r}")


@dataclass(frozen=True, slots=True)
class PasswordHash:
    """密码哈希：只接受 bcrypt 形态，禁止明文（不变式 1）。"""

    value: str

    def __post_init__(self) -> None:
        if not self.value.startswith("$2"):
            raise DomainValidationError("密码必须以 bcrypt 哈希存储，禁止明文")


@dataclass(frozen=True, slots=True)
class Nickname:
    """用户昵称（F10）：1~30 字，允许重名。"""

    value: str

    def __post_init__(self) -> None:
        cleaned = _normalize_profile_text(
            self.value, field_name="昵称", max_length=_NICKNAME_MAX_LENGTH
        )
        object.__setattr__(self, "value", cleaned)


@dataclass(frozen=True, slots=True)
class College:
    """学院（F10）：1~64 字。"""

    value: str

    def __post_init__(self) -> None:
        cleaned = _normalize_profile_text(
            self.value, field_name="学院", max_length=_CAMPUS_META_MAX_LENGTH
        )
        object.__setattr__(self, "value", cleaned)


@dataclass(frozen=True, slots=True)
class ClassName:
    """班级（F10）：1~64 字。"""

    value: str

    def __post_init__(self) -> None:
        cleaned = _normalize_profile_text(
            self.value, field_name="班级", max_length=_CAMPUS_META_MAX_LENGTH
        )
        object.__setattr__(self, "value", cleaned)


@dataclass(frozen=True, slots=True)
class VerificationCode:
    """邮箱验证码（F10）：仅 6 位 ASCII 数字。"""

    value: str

    def __post_init__(self) -> None:
        reject_unsafe_text(self.value, field_name="验证码")
        if not _VERIFICATION_CODE_PATTERN.match(self.value):
            raise DomainValidationError("验证码必须为 6 位数字")
