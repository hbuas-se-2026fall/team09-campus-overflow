from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from app.contexts.identity.domain.errors import IdentityRequiredError, WeakPasswordError
from app.contexts.identity.domain.value_objects import (
    ClassName,
    College,
    Email,
    Nickname,
    PasswordHash,
    StaffId,
    StudentId,
)
from app.shared.sentinel import UNSET, UnsetType

Role = Literal["student", "teacher"]

_PASSWORD_MIN_LENGTH = 8
_HAS_LETTER = re.compile(r"[A-Za-z]")
_HAS_DIGIT = re.compile(r"\d")


def validate_password_strength(plain: str) -> None:
    """密码强度不变式：至少 8 位且同时含字母和数字（US-R04）。"""
    too_short = len(plain) < _PASSWORD_MIN_LENGTH
    if too_short or not _HAS_LETTER.search(plain) or not _HAS_DIGIT.search(plain):
        raise WeakPasswordError("密码至少 8 位且需同时包含字母和数字")


def normalize_public_nickname(nickname: str | None) -> str | None:
    """清洗公开昵称（兼容历史空串/首尾空白，保证 display_name 与 nickname 口径一致）。"""
    if nickname is None:
        return None
    cleaned = nickname.strip()
    return cleaned if cleaned else None


_ROLE_DISPLAY_PREFIXES: dict[str, str] = {
    "teacher": "教师",
    "student": "学生",
}


def resolve_display_name(
    role: Role | str,
    user_id: UUID,
    nickname: str | None,
) -> str:
    """公开展示名唯一计算规则（F11）：优先昵称，否则按角色 + 8 位 hex 兜底，绝不泄露学工号/邮箱。"""
    cleaned = normalize_public_nickname(nickname)
    if cleaned is not None:
        return cleaned
    # 未知/未来扩展角色回退通用“用户”前缀，避免误标为“学生”
    prefix = _ROLE_DISPLAY_PREFIXES.get(role, "用户")
    return f"{prefix}#{user_id.hex[:8]}"


@dataclass(frozen=True, slots=True)
class UserRegistered:
    """领域事件：用户注册完成。"""

    user_id: UUID
    role: str
    occurred_at: datetime


@dataclass
class User:
    """用户聚合根：学生或教师，身份二选一（不变式 4）。"""

    id: UUID
    role: Role
    email: Email
    password_hash: PasswordHash
    student_id: StudentId | None
    staff_id: StaffId | None
    created_at: datetime
    nickname: Nickname | None = None
    college: College | None = None
    class_name: ClassName | None = None
    email_verified: bool = False
    events: list[UserRegistered] = field(default_factory=list, repr=False, compare=False)

    def update_profile(
        self,
        *,
        nickname: Nickname | None | UnsetType = UNSET,
        college: College | None | UnsetType = UNSET,
        class_name: ClassName | None | UnsetType = UNSET,
    ) -> None:
        if not isinstance(nickname, UnsetType):
            self.nickname = nickname
        if not isinstance(college, UnsetType):
            self.college = college
        if not isinstance(class_name, UnsetType):
            self.class_name = class_name

    def mark_email_verified(self) -> None:
        self.email_verified = True

    @property
    def display_name(self) -> str:
        """当前用户的公开展示名（复用单源规则，不泄露学工号/邮箱）。"""
        return resolve_display_name(
            self.role,
            self.id,
            self.nickname.value if self.nickname is not None else None,
        )

    @classmethod
    def register(
        cls,
        *,
        role: Role,
        email_value: str,
        password_hash_value: str,
        identity_value: str | None,
    ) -> User:
        student_id: StudentId | None = None
        staff_id: StaffId | None = None

        if role == "student":
            if identity_value is None:
                raise IdentityRequiredError("学生注册必须提供学号")
            student_id = StudentId(identity_value)
        elif role == "teacher":
            if identity_value is None:
                raise IdentityRequiredError("教师注册必须提供工号")
            staff_id = StaffId(identity_value)

        now = datetime.now(UTC)
        user = cls(
            id=uuid4(),
            role=role,
            email=Email(email_value),
            password_hash=PasswordHash(password_hash_value),
            student_id=student_id,
            staff_id=staff_id,
            created_at=now,
        )
        user.events.append(UserRegistered(user_id=user.id, role=role, occurred_at=now))
        return user
