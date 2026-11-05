"""reputation 应用层端口与跨上下文事件契约。

- VoteEventPayload / AcceptEventPayload：跨上下文已发布语言（qa 侧按字段构造，
  reputation 侧消费），保证 reputation 对 qa **0 import**。
- EventPublisher：出站端口，Celery 适配器在 infrastructure 实现；
  投递时机（commit 后）由 interfaces 层的延迟门面负责，端口本身不感知框架。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, slots=True)
class VoteEventPayload:
    """投票事件 DTO（来源：qa VoteCast 字段映射；字段一一对应）。"""

    vote_id: UUID
    user_id: UUID
    target_type: str
    target_id: UUID
    direction: str
    target_author_id: UUID
    occurred_at: datetime


@dataclass(frozen=True, slots=True)
class AcceptEventPayload:
    """采纳事件 DTO（来源：qa AnswerAccepted 字段映射）。"""

    event_id: UUID
    answer_id: UUID
    answer_author_id: UUID
    occurred_at: datetime


class EventPublisher(Protocol):
    """声誉事件发布端口：application 定义，infrastructure 提供实现。"""

    def publish_vote(self, payload: VoteEventPayload) -> None:
        """投递投票事件（reputation.apply_vote_delta）。"""
        ...

    def publish_accept(self, payload: AcceptEventPayload) -> None:
        """投递采纳事件（reputation.apply_accept_bonus）。"""
        ...
