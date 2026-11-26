"""discovery 通知领域枚举与工厂单测（F04 / F14，无外部依赖，进 CI）。"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.contexts.discovery.domain.notification import (
    NotificationTargetType,
    NotificationType,
    build_notification,
)


def test_notification_enums_include_comment_replied_and_comment_target() -> None:
    assert NotificationType.COMMENT_REPLIED.value == "comment_replied"
    assert NotificationType.ANSWER_VERIFIED.value == "answer_verified"
    assert len(NotificationType.ANSWER_VERIFIED.value) <= 20
    assert NotificationTargetType.COMMENT.value == "comment"


def test_build_notification_for_answer_verified() -> None:
    recipient, actor, aid, event_id, qid = uuid4(), uuid4(), uuid4(), uuid4(), uuid4()
    notification = build_notification(
        recipient_id=recipient,
        type="answer_verified",
        actor_id=actor,
        target_type="answer",
        target_id=aid,
        source_event_id=event_id,
        question_id=qid,
    )
    assert notification.type is NotificationType.ANSWER_VERIFIED
    assert notification.target_type is NotificationTargetType.ANSWER
    assert notification.target_id == aid
    assert notification.question_id == qid


def test_build_notification_for_comment_reply() -> None:
    recipient, actor, parent_cid, comment_id, qid = (
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
        uuid4(),
    )
    notification = build_notification(
        recipient_id=recipient,
        type="comment_replied",
        actor_id=actor,
        target_type="comment",
        target_id=parent_cid,
        source_event_id=comment_id,
        question_id=qid,
    )
    assert notification.type is NotificationType.COMMENT_REPLIED
    assert notification.target_type is NotificationTargetType.COMMENT
    assert notification.target_id == parent_cid
    assert notification.source_event_id == comment_id
    assert notification.question_id == qid
    assert notification.is_read is False


def test_build_notification_rejects_unknown_enum_values() -> None:
    with pytest.raises(ValueError):
        build_notification(
            recipient_id=uuid4(),
            type="unknown_type",
            actor_id=uuid4(),
            target_type="comment",
            target_id=uuid4(),
            source_event_id=uuid4(),
        )
    with pytest.raises(ValueError):
        build_notification(
            recipient_id=uuid4(),
            type="comment_replied",
            actor_id=uuid4(),
            target_type="unknown_target",
            target_id=uuid4(),
            source_event_id=uuid4(),
        )
