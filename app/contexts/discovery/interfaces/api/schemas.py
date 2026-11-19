"""通知接口 schema（F04）：白名单响应。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class NotificationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    type: str
    actor_id: UUID
    actor_name: str
    target_type: str
    target_id: UUID
    question_id: UUID | None = None
    is_read: bool
    created_at: datetime


class NotificationListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[NotificationResponse]
    total: int
    page: int
    page_size: int
    total_pages: int


class UnreadCountResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    count: int


class ReadAllResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    updated: int
