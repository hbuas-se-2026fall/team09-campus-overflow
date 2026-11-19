"""当前用户积分余额与流水路由（F07 闭环）。"""

from __future__ import annotations

from fastapi import APIRouter

from app.contexts.identity.interfaces.api.deps import CurrentUser
from app.contexts.qa.application.get_my_points_use_case import GetMyPointsUseCase
from app.contexts.qa.interfaces.api.deps import PointsRepo
from app.contexts.qa.interfaces.api.schemas import (
    MyPointsResponse,
    PointEntryResponse,
)

points_router = APIRouter(prefix="/api/v1/users/me", tags=["points"])


@points_router.get(
    "/points",
    response_model=MyPointsResponse,
    summary="查询本人可消费积分余额与流水（需登录；教师首次访问惰性发放初始额度）",
)
async def get_my_points(
    user: CurrentUser,
    points: PointsRepo,
) -> MyPointsResponse:
    view = await GetMyPointsUseCase(points).execute(user.id, user.role)
    return MyPointsResponse(
        balance=view.balance,
        entries=[
            PointEntryResponse(
                source=entry.source,
                event_id=entry.event_id,
                delta=entry.delta,
                reason=entry.reason,
                occurred_at=entry.occurred_at,
            )
            for entry in view.entries
        ],
    )
