"""通知路由（F04，discovery）：列表 / 单条已读 / 全部已读 / 未读数。

全部端点要求登录；收件人恒取令牌当前用户，绝不取自请求参数。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.contexts.discovery.application.get_unread_count_use_case import (
    GetUnreadCountUseCase,
)
from app.contexts.discovery.application.list_notifications_use_case import (
    ListNotificationsUseCase,
)
from app.contexts.discovery.application.mark_notification_read_use_case import (
    MarkAllNotificationsReadUseCase,
    MarkNotificationReadUseCase,
)
from app.contexts.discovery.domain.notification import Notification
from app.contexts.discovery.interfaces.api.deps import NotificationRepo
from app.contexts.discovery.interfaces.api.schemas import (
    NotificationListResponse,
    NotificationResponse,
    ReadAllResponse,
    UnreadCountResponse,
)
from app.contexts.identity.interfaces.api.deps import CurrentUser

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


def _response(notification: Notification) -> NotificationResponse:
    return NotificationResponse(
        id=notification.id,
        type=notification.type.value,
        actor_id=notification.actor_id,
        target_type=notification.target_type.value,
        target_id=notification.target_id,
        question_id=notification.question_id,
        is_read=notification.is_read,
        created_at=notification.created_at,
    )


@router.get(
    "",
    response_model=NotificationListResponse,
    summary="通知列表（仅本人；分页 + 未读筛选）",
)
async def list_notifications(
    user: CurrentUser,
    notifications: NotificationRepo,
    page: int = Query(default=1, ge=1, description="页码，从 1 起"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数，上限 100"),
    unread_only: bool = Query(default=False, description="只看未读"),
) -> NotificationListResponse:
    view = await ListNotificationsUseCase(notifications).execute(
        user.id, page, page_size, unread_only
    )
    return NotificationListResponse(
        items=[_response(n) for n in view.items],
        total=view.total,
        page=view.page,
        page_size=view.page_size,
        total_pages=view.total_pages,
    )


@router.get(
    "/unread-count",
    response_model=UnreadCountResponse,
    summary="未读通知数（仅本人）",
)
async def unread_count(
    user: CurrentUser, notifications: NotificationRepo
) -> UnreadCountResponse:
    count = await GetUnreadCountUseCase(notifications).execute(user.id)
    return UnreadCountResponse(count=count)


@router.post(
    "/{notification_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="单条标记已读（仅本人；幂等 204，非本人/不存在 404）",
)
async def mark_notification_read(
    notification_id: UUID,
    user: CurrentUser,
    notifications: NotificationRepo,
) -> Response:
    ok = await MarkNotificationReadUseCase(notifications).execute(
        notification_id, user.id
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="通知不存在"
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/read-all",
    response_model=ReadAllResponse,
    summary="全部标记已读（仅本人；返回本次更新条数，幂等）",
)
async def mark_all_notifications_read(
    user: CurrentUser, notifications: NotificationRepo
) -> ReadAllResponse:
    updated = await MarkAllNotificationsReadUseCase(notifications).execute(user.id)
    return ReadAllResponse(updated=updated)
