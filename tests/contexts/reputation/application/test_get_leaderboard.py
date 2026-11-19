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
        self.calls: list[tuple[datetime, datetime, int]] = []

    @property
    def last_call(self) -> tuple[datetime, datetime, int] | None:
        return self.calls[-1] if self.calls else None

    async def list_top(
        self, start: datetime, end: datetime, limit: int
    ) -> list[LeaderboardRow]:
        self.calls.append((start, end, limit))
        return self.rows[:limit]


class FakeLeaderboardCache:
    def __init__(self) -> None:
        self.store: dict[tuple[LeaderboardPeriod, int, datetime], list[LeaderboardRow]] = {}
        self.get_calls: list[tuple[LeaderboardPeriod, int, datetime]] = []
        self.set_calls: list[tuple[LeaderboardPeriod, int, datetime, int]] = []

    async def get(
        self, period: LeaderboardPeriod, limit: int, start: datetime
    ) -> list[LeaderboardRow] | None:
        key = (period, limit, start)
        self.get_calls.append(key)
        return self.store.get(key)

    async def set(
        self,
        period: LeaderboardPeriod,
        limit: int,
        start: datetime,
        rows: list[LeaderboardRow],
        ttl_seconds: int,
    ) -> None:
        self.store[(period, limit, start)] = list(rows)
        self.set_calls.append((period, limit, start, ttl_seconds))


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


async def test_leaderboard_cache_miss_populates_then_hits_without_db() -> None:
    repo = FakeLedgerRepository()
    row = LeaderboardRow(user_id=uuid4(), score=88, rank=1)
    repo.rows = [row]
    cache = FakeLeaderboardCache()
    now = datetime(2026, 3, 4, 12, tzinfo=timezone(timedelta(hours=8)))
    use_case = GetLeaderboardUseCase(repo, cache=cache, cache_ttl_seconds=45)

    first = await use_case.execute(LeaderboardPeriod.WEEK, 10, now=now)
    repo.rows = []  # 后续改库不应影响缓存命中
    second = await use_case.execute(LeaderboardPeriod.WEEK, 10, now=now)

    assert first.entries == [row]
    assert second.entries == [row]
    assert len(repo.calls) == 1
    assert len(cache.set_calls) == 1
    assert cache.set_calls[0][3] == 45


async def test_leaderboard_cache_distinguishes_empty_list_hit_from_miss() -> None:
    repo = FakeLedgerRepository()
    cache = FakeLeaderboardCache()
    now = datetime(2026, 3, 4, 12, tzinfo=timezone(timedelta(hours=8)))
    use_case = GetLeaderboardUseCase(repo, cache=cache, cache_ttl_seconds=60)

    first = await use_case.execute(LeaderboardPeriod.MONTH, 10, now=now)
    second = await use_case.execute(LeaderboardPeriod.MONTH, 10, now=now)

    assert first.entries == []
    assert second.entries == []
    assert len(repo.calls) == 1
    assert len(cache.set_calls) == 1


async def test_leaderboard_cache_isolates_across_period_boundaries() -> None:
    repo = FakeLedgerRepository()
    cache = FakeLeaderboardCache()
    use_case = GetLeaderboardUseCase(repo, cache=cache, cache_ttl_seconds=60)
    week1 = datetime(2026, 3, 4, 12, tzinfo=timezone(timedelta(hours=8)))
    week2 = datetime(2026, 3, 11, 12, tzinfo=timezone(timedelta(hours=8)))

    row1 = LeaderboardRow(user_id=uuid4(), score=10, rank=1)
    row2 = LeaderboardRow(user_id=uuid4(), score=20, rank=1)
    repo.rows = [row1]
    v1 = await use_case.execute(LeaderboardPeriod.WEEK, 10, now=week1)
    repo.rows = [row2]
    v2 = await use_case.execute(LeaderboardPeriod.WEEK, 10, now=week2)

    assert v1.entries == [row1]
    assert v2.entries == [row2]
    assert len(repo.calls) == 2


async def test_leaderboard_non_positive_ttl_bypasses_cache() -> None:
    repo = FakeLedgerRepository()
    cache = FakeLeaderboardCache()
    use_case = GetLeaderboardUseCase(repo, cache=cache, cache_ttl_seconds=0)

    await use_case.execute(LeaderboardPeriod.WEEK, 10)
    await use_case.execute(LeaderboardPeriod.WEEK, 10)

    assert len(repo.calls) == 2
    assert cache.get_calls == []
    assert cache.set_calls == []
