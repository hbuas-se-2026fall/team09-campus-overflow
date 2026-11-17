"""reputation 接口路由：本人声誉查询（US-REP02）+ 公开排行榜（F05）。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.config.settings import get_settings
from app.contexts.identity.interfaces.api.deps import CurrentUser
from app.contexts.reputation.application.get_leaderboard_use_case import (
    GetLeaderboardUseCase,
)
from app.contexts.reputation.application.get_reputation_use_case import GetReputationUseCase
from app.contexts.reputation.domain.leaderboard import LeaderboardPeriod
from app.contexts.reputation.interfaces.api.deps import (
    LeaderboardCacheDep,
    ReputationLedgerRepo,
)
from app.contexts.reputation.interfaces.api.schemas import (
    LeaderboardEntryResponse,
    LeaderboardResponse,
    ReputationEntryResponse,
    ReputationResponse,
)

reputation_router = APIRouter(prefix="/api/v1/users", tags=["reputation"])
leaderboard_router = APIRouter(prefix="/api/v1/leaderboard", tags=["leaderboard"])


@reputation_router.get(
    "/{user_id}/reputation",
    response_model=ReputationResponse,
    summary="查询本人声誉总值与变动流水（仅本人，US-REP02；他人 403）",
)
async def get_reputation(
    user_id: UUID,
    user: CurrentUser,
    ledger: ReputationLedgerRepo,
) -> ReputationResponse:
    """仅本人可见（v3.1 裁定 4；Gherkin 功能域 11 场景 3 字面"查询自己的声誉"）。

    403（非 404）：user_id 在问题/回答的 author_id 已公开，无存在性可泄露，
    403 语义最准确；流水为空时返回 total=0 + 空列表（200）。
    """
    if user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="仅可查询本人声誉"
        )
    use_case = GetReputationUseCase(ledger)
    view = await use_case.execute(user_id)
    return ReputationResponse(
        user_id=view.user_id,
        total=view.total,
        entries=[
            ReputationEntryResponse(
                source=e.source.value,
                event_id=e.event_id,
                delta=e.delta,
                reason=e.reason,
                occurred_at=e.occurred_at,
            )
            for e in view.entries
        ],
    )


@leaderboard_router.get(
    "",
    response_model=LeaderboardResponse,
    summary="排行榜：周/月/学期 Top N（公开；净得分，同分同名次）",
)
async def get_leaderboard(
    ledger: ReputationLedgerRepo,
    cache: LeaderboardCacheDep,
    period: LeaderboardPeriod = Query(
        default=LeaderboardPeriod.WEEK,
        description="周期：week=本周；month=本月；semester=当前学期（D10 学期待口径）",
    ),
    limit: int = Query(default=10, ge=1, le=100, description="返回条数，1~100"),
) -> LeaderboardResponse:
    ttl = get_settings().leaderboard_cache_ttl_seconds
    view = await GetLeaderboardUseCase(
        ledger, cache=cache, cache_ttl_seconds=ttl
    ).execute(period, limit)
    return LeaderboardResponse(
        period=view.period,
        period_start=view.period_start,
        period_end=view.period_end,
        entries=[
            LeaderboardEntryResponse(
                user_id=e.user_id, score=e.score, rank=e.rank
            )
            for e in view.entries
        ],
    )
