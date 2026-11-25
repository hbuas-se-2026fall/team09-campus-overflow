"""举报聚合与值对象（F18：仅支持 question / answer，含单源理由与处理备注校验）。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.shared.errors import DomainValidationError
from app.shared.text_validation import reject_unsafe_text

_REASON_MIN_LENGTH = 5
_REASON_MAX_LENGTH = 500
_NOTE_MIN_LENGTH = 1
_NOTE_MAX_LENGTH = 500


class ReportTargetType(StrEnum):
    """举报目标类型：定死为 question 与 answer（不含 comment）。"""

    QUESTION = "question"
    ANSWER = "answer"


class ReportStatus(StrEnum):
    """举报工单状态机。"""

    PENDING = "pending"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


class ReportAction(StrEnum):
    """管理员处置动作（OCP 策略键）。"""

    DISMISS = "dismiss"
    CLOSE_QUESTION = "close_question"
    SOFT_DELETE = "soft_delete"


@dataclass(frozen=True, slots=True)
class ReportReason:
    """举报理由：去首尾空白后 5~500 字。"""

    value: str

    def __post_init__(self) -> None:
        reject_unsafe_text(self.value, field_name="举报理由")
        cleaned = self.value.strip()
        if not (_REASON_MIN_LENGTH <= len(cleaned) <= _REASON_MAX_LENGTH):
            raise DomainValidationError(
                f"举报理由需 {_REASON_MIN_LENGTH}~{_REASON_MAX_LENGTH} 字"
                f"（去首尾空白后），实际 {len(cleaned)} 字"
            )
        object.__setattr__(self, "value", cleaned)


@dataclass(frozen=True, slots=True)
class ResolutionNote:
    """管理员处理备注：去首尾空白后 1~500 字。"""

    value: str

    def __post_init__(self) -> None:
        reject_unsafe_text(self.value, field_name="处理备注")
        cleaned = self.value.strip()
        if not (_NOTE_MIN_LENGTH <= len(cleaned) <= _NOTE_MAX_LENGTH):
            raise DomainValidationError(
                f"处理备注需 {_NOTE_MIN_LENGTH}~{_NOTE_MAX_LENGTH} 字"
                f"（去首尾空白后），实际 {len(cleaned)} 字"
            )
        object.__setattr__(self, "value", cleaned)


def normalize_resolution_note(raw: str | None) -> ResolutionNote | None:
    """单源处理备注规范化：None 或纯空白返回 None，危险字符即时拒绝。"""
    if raw is None:
        return None
    reject_unsafe_text(raw, field_name="处理备注")
    cleaned = raw.strip()
    if not cleaned:
        return None
    return ResolutionNote(cleaned)


@dataclass(slots=True)
class Report:
    """内容举报聚合根。"""

    id: UUID
    reporter_id: UUID
    target_type: ReportTargetType
    target_id: UUID
    reason: ReportReason
    status: ReportStatus
    created_at: datetime
    resolution_action: ReportAction | None = None
    resolution_note: ResolutionNote | None = None
    resolved_by: UUID | None = None
    resolved_at: datetime | None = None

    @classmethod
    def file(
        cls,
        *,
        reporter_id: UUID,
        target_type: ReportTargetType,
        target_id: UUID,
        reason: str,
    ) -> Report:
        return cls(
            id=uuid4(),
            reporter_id=reporter_id,
            target_type=target_type,
            target_id=target_id,
            reason=ReportReason(reason),
            status=ReportStatus.PENDING,
            created_at=datetime.now(UTC),
        )
