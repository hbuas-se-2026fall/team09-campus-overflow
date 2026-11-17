"""排行榜用例单测（F05）：周期解析与仓储委托，不连库，进 CI。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

from app.contexts.reputation.application.get_leaderboard_use_case import (
    GetLeaderboardUseCase,
)
from app.contexts.reputation.domain.leaderboard import (
    LeaderboardPeriod,
    LeaderboardRow,
)


class FakeLedgerRepository:
    def __init__(self) -> None:
        self.rows: list[LeaderboardRow] = []
        self.last_call: tuple[datetime, datetime, int] | None = None

    async def list_top(
        self, start: datetime, end: datetime, limit: int
    ) -> list[LeaderboardRow]:
        self.last_call = (start, end, limit)
        return self.rows[:limit]


async def test_leaderboard_resolves_period_and_delegates_limit() -> None:
    repo = FakeLedgerRepository()
    row = LeaderboardRow(user_id=uuid4(), score=42, rank=1)
    repo.rows = [row]
    now = datetime(2026, 3, 4, 12, tzinfo=timezone(timedelta(hours=8)))

    view = await GetLeaderboardUseCase(repo).execute(
        LeaderboardPeriod.WEEK, 5, now=now
    )

    assert view.period is LeaderboardPeriod.WEEK
    assert view.entries == [row]
    assert view.period_start == datetime(2026, 3, 1, 16, tzinfo=UTC)
    assert view.period_end == datetime(2026, 3, 8, 16, tzinfo=UTC)
    assert repo.last_call == (view.period_start, view.period_end, 5)


async def test_leaderboard_empty_returns_empty_entries() -> None:
    repo = FakeLedgerRepository()
    view = await GetLeaderboardUseCase(repo).execute(LeaderboardPeriod.MONTH, 10)
    assert view.entries == []
