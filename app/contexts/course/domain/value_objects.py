"""course 上下文领域值对象：全部清洗与不变式校验收敛于 __post_init__。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.shared.errors import DomainValidationError
from app.shared.text_validation import reject_unsafe_text

_COURSE_CODE_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9_-]{1,31}\Z")
_COURSE_NAME_MIN_LENGTH = 2
_COURSE_NAME_MAX_LENGTH = 100
_SEMESTER_MIN_LENGTH = 2
_SEMESTER_MAX_LENGTH = 32
_FORBIDDEN_WHITESPACE_CHARS = ("\t", "\n", "\r")


def _validate_single_line_text(
    raw: str,
    *,
    field_name: str,
    min_length: int,
    max_length: int,
) -> str:
    reject_unsafe_text(raw, field_name=field_name)
    if any(ch in raw for ch in _FORBIDDEN_WHITESPACE_CHARS):
        raise DomainValidationError(f"{field_name}不能包含制表符或换行符")
    normalized = raw.strip()
    if not (min_length <= len(normalized) <= max_length):
        raise DomainValidationError(
            f"{field_name}需 {min_length}~{max_length} 个字符（去首尾空白后），"
            f"实际 {len(normalized)} 个字符"
        )
    return normalized


@dataclass(frozen=True, slots=True)
class CourseCode:
    """课程编号：去首尾空白并转大写，2~32 位字母/数字/下划线/连字符。"""

    value: str

    def __post_init__(self) -> None:
        reject_unsafe_text(self.value, field_name="课程编号")
        if any(ch in self.value for ch in _FORBIDDEN_WHITESPACE_CHARS):
            raise DomainValidationError("课程编号不能包含制表符或换行符")
        normalized = self.value.strip().upper()
        if not _COURSE_CODE_PATTERN.match(normalized):
            raise DomainValidationError(
                "课程编号格式不合法：须为 2~32 位字母或数字开头，仅含字母、数字、下划线与连字符"
            )
        object.__setattr__(self, "value", normalized)


@dataclass(frozen=True, slots=True)
class CourseName:
    """课程名称：单行文本，去首尾空白后 2~100 个字符。"""

    value: str

    def __post_init__(self) -> None:
        normalized = _validate_single_line_text(
            self.value,
            field_name="课程名称",
            min_length=_COURSE_NAME_MIN_LENGTH,
            max_length=_COURSE_NAME_MAX_LENGTH,
        )
        object.__setattr__(self, "value", normalized)


@dataclass(frozen=True, slots=True)
class Semester:
    """学期标识：单行文本，去首尾空白后 2~32 个字符（如 2026-Fall、2026秋）。"""

    value: str

    def __post_init__(self) -> None:
        normalized = _validate_single_line_text(
            self.value,
            field_name="学期",
            min_length=_SEMESTER_MIN_LENGTH,
            max_length=_SEMESTER_MAX_LENGTH,
        )
        object.__setattr__(self, "value", normalized)
