"""通知聚合（F04，discovery）：站内通知，只追加；已读为唯一可变状态。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4


class NotificationType(StrEnum):
    """站内通知类型（F04 基础三类 + F14 评论二级回复 + F15 教师认证回答）。"""

    ANSWER_POSTED = "answer_posted"
    ANSWER_ACCEPTED = "answer_accepted"
    ANSWER_VERIFIED = "answer_verified"
    COMMENT_CREATED = "comment_created"
    COMMENT_REPLIED = "comment_replied"


class NotificationTargetType(StrEnum):
    """通知指向的资源类型（F04 问题/回答 + F14 评论）。"""

    QUESTION = "question"
    ANSWER = "answer"
    COMMENT = "comment"


@dataclass(frozen=True, slots=True)
class Notification:
    id: UUID
    recipient_id: UUID
    type: NotificationType
    actor_id: UUID
    target_type: NotificationTargetType
    target_id: UUID
    source_event_id: UUID
    is_read: bool
    created_at: datetime
    question_id: UUID | None = None


def build_notification(
    *,
    recipient_id: UUID,
    type: NotificationType | str,
    actor_id: UUID,
    target_type: NotificationTargetType | str,
    target_id: UUID,
    source_event_id: UUID,
    question_id: UUID | None = None,
) -> Notification:
    """构造未读通知；同事件幂等由库级 (type, source_event_id, recipient_id) 唯一约束兜底。"""
    return Notification(
        id=uuid4(),
        recipient_id=recipient_id,
        type=NotificationType(type),
        actor_id=actor_id,
        target_type=NotificationTargetType(target_type),
        target_id=target_id,
        source_event_id=source_event_id,
        is_read=False,
        created_at=datetime.now(UTC),
        question_id=question_id,
    )
