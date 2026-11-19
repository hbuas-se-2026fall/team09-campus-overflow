"""用户徽章路由（F06，公开）：实时统计回答数/采纳率/最长连续活跃天数。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.contexts.identity.interfaces.api.deps import UserRepo
from app.contexts.qa.application.get_user_badges_use_case import GetUserBadgesUseCase
from app.contexts.qa.interfaces.api.deps import UserActivityRepo
from app.contexts.qa.interfaces.api.schemas import BadgeResponse, UserBadgesResponse

router = APIRouter(prefix="/api/v1/users", tags=["badges"])


@router.get(
    "/{user_id}/badges",
    response_model=UserBadgesResponse,
    summary="用户徽章（公开；F06：回答数/采纳率/历史最长连续活跃）",
)
async def get_user_badges(
    user_id: UUID,
    users: UserRepo,
    activity: UserActivityRepo,
) -> UserBadgesResponse:
    # 用户不存在 → 404（与详情口径一致，不泄露内部信息）
    if await users.get_by_id(user_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    view = await GetUserBadgesUseCase(activity).execute(user_id)
    return UserBadgesResponse(
        user_id=view.user_id,
        answer_count=view.answer_count,
        accepted_count=view.accepted_count,
        acceptance_rate=view.acceptance_rate,
        longest_streak_days=view.longest_streak_days,
        badges=[
            BadgeResponse(
                code=b.code,
                kind=b.kind.value,
                tier=b.tier.value,
                threshold=b.threshold,
            )
            for b in view.badges
        ],
    )
