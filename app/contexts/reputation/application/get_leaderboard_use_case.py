"""排行榜用例（F05，只读）：周期解析 + 仓储聚合，公开访问。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.contexts.reputation.application.ports import LeaderboardCache
from app.contexts.reputation.domain.leaderboard import (
    LeaderboardPeriod,
    LeaderboardRow,
    resolve_period_range,
)
from app.contexts.reputation.domain.repository import ReputationLedgerRepository


@dataclass(frozen=True, slots=True)
class LeaderboardView:
    """榜单视图：周期元信息 + Top N 行（名次由仓储 SQL 计算）。"""

    period: LeaderboardPeriod
    period_start: datetime
    period_end: datetime
    entries: list[LeaderboardRow]


class GetLeaderboardUseCase:
    def __init__(
        self,
        repository: ReputationLedgerRepository,
        cache: LeaderboardCache | None = None,
        cache_ttl_seconds: int = 60,
    ) -> None:
        self._repository = repository
        self._cache = cache
        self._cache_ttl_seconds = cache_ttl_seconds

    async def execute(
        self,
        period: LeaderboardPeriod,
        limit: int,
        *,
        now: datetime | None = None,
    ) -> LeaderboardView:
        start, end = resolve_period_range(period, now=now)
        if self._cache is not None and self._cache_ttl_seconds > 0:
            cached = await self._cache.get(period, limit, start)
            if cached is not None:
                return LeaderboardView(
                    period=period,
                    period_start=start,
                    period_end=end,
                    entries=cached,
                )

        entries = await self._repository.list_top(start, end, limit)
        if self._cache is not None and self._cache_ttl_seconds > 0:
            await self._cache.set(
                period, limit, start, entries, self._cache_ttl_seconds
            )
        return LeaderboardView(
            period=period,
            period_start=start,
            period_end=end,
            entries=entries,
        )
