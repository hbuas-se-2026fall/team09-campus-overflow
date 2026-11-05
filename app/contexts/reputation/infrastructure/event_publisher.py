"""声誉事件发布适配器（Celery 实现）：DTO → JSON 安全 dict → .delay。

序列化单源：领域/应用层只产出 DTO（UUID/datetime 原生类型），本适配器负责
kombu JSON 所需的叶子转换（UUID → str、datetime → isoformat），worker 入口
（tasks._to_uuid/_to_datetime）负责回转。发布失败（broker 不可达等）只记日志：
已知的 at-most-once 窗口，ADR-004 登记其后果与阶段 4 演进方向（outbox）。
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import datetime
from typing import Any
from uuid import UUID

from app.contexts.reputation.application.ports import (
    AcceptEventPayload,
    VoteEventPayload,
)
from app.contexts.reputation.infrastructure.tasks import (
    apply_accept_bonus,
    apply_vote_delta,
)

logger = logging.getLogger(__name__)


def _json_safe(payload: VoteEventPayload | AcceptEventPayload) -> dict[str, Any]:
    """DTO → JSON 安全 dict（UUID→str、datetime→isoformat；StrEnum 即 str）。"""
    return {
        key: (
            str(value)
            if isinstance(value, UUID)
            else value.isoformat()
            if isinstance(value, datetime)
            else value
        )
        for key, value in asdict(payload).items()
    }


class CeleryEventPublisher:
    """EventPublisher 端口的 Celery 实现。"""

    def publish_vote(self, payload: VoteEventPayload) -> None:
        self._publish(apply_vote_delta, payload)

    def publish_accept(self, payload: AcceptEventPayload) -> None:
        self._publish(apply_accept_bonus, payload)

    @staticmethod
    def _publish(task: Any, payload: VoteEventPayload | AcceptEventPayload) -> None:
        try:
            task.delay(_json_safe(payload))
        except Exception:
            logger.exception(
                "声誉事件发布失败（at-most-once 窗口，ADR-004）: task=%s payload=%s",
                getattr(task, "name", task),
                payload,
            )
