"""排行榜 Redis 缓存适配器单测（F08）：纯内存桩，不连外部 Redis，进 CI。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

from redis.exceptions import RedisError

from app.contexts.reputation.domain.leaderboard import LeaderboardPeriod, LeaderboardRow
from app.contexts.reputation.infrastructure.leaderboard_cache import RedisLeaderboardCache


class FakeAsyncRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}
        self.fail_get = False
        self.fail_set = False

    async def get(self, key: str) -> str | None:
        if self.fail_get:
            raise RedisError("connection refused")
        return self.data.get(key)

    async def set(self, key: str, value: str, *, ex: int) -> None:
        if self.fail_set:
            raise RedisError("read only")
        self.data[key] = value
        self.ttls[key] = ex


def _cache_with_fake() -> tuple[RedisLeaderboardCache, FakeAsyncRedis]:
    fake = FakeAsyncRedis()
    cache: RedisLeaderboardCache = RedisLeaderboardCache(lambda: fake)  # type: ignore[arg-type,return-value]
    return cache, fake


async def test_cache_roundtrip_and_empty_list_distinction() -> None:
    cache, fake = _cache_with_fake()
    start = datetime(2026, 3, 1, 16, tzinfo=UTC)

    assert await cache.get(LeaderboardPeriod.WEEK, 10, start) is None

    await cache.set(LeaderboardPeriod.WEEK, 10, start, [], 60)
    assert await cache.get(LeaderboardPeriod.WEEK, 10, start) == []
    assert list(fake.ttls.values()) == [60]

    rows = [
        LeaderboardRow(user_id=uuid4(), score=15, rank=1),
        LeaderboardRow(user_id=uuid4(), score=-2, rank=2),
    ]
    await cache.set(LeaderboardPeriod.WEEK, 10, start, rows, 45)
    assert await cache.get(LeaderboardPeriod.WEEK, 10, start) == rows


async def test_cache_normalizes_start_timezone_to_utc() -> None:
    cache, _ = _cache_with_fake()
    utc_start = datetime(2026, 3, 1, 16, tzinfo=UTC)
    shanghai_start = datetime(2026, 3, 2, 0, tzinfo=timezone(timedelta(hours=8)))
    rows = [LeaderboardRow(user_id=uuid4(), score=10, rank=1)]

    await cache.set(LeaderboardPeriod.WEEK, 10, shanghai_start, rows, 60)
    assert await cache.get(LeaderboardPeriod.WEEK, 10, utc_start) == rows


async def test_cache_degrades_to_none_on_corrupted_payload() -> None:
    cache, fake = _cache_with_fake()
    start = datetime(2026, 3, 1, 16, tzinfo=UTC)
    rows = [LeaderboardRow(user_id=uuid4(), score=10, rank=1)]
    await cache.set(LeaderboardPeriod.WEEK, 10, start, rows, 60)
    key = next(iter(fake.data))

    for bad_raw in (
        "{not-json",
        '{"not":"a-list"}',
        '[{"user_id":"bad-uuid","score":1,"rank":1}]',
        '[{"user_id":"00000000-0000-0000-0000-000000000001","score":true,"rank":1}]',
    ):
        fake.data[key] = bad_raw
        assert await cache.get(LeaderboardPeriod.WEEK, 10, start) is None


async def test_cache_degrades_gracefully_on_redis_error() -> None:
    cache, fake = _cache_with_fake()
    start = datetime(2026, 3, 1, 16, tzinfo=UTC)
    rows = [LeaderboardRow(user_id=uuid4(), score=10, rank=1)]

    fake.fail_get = True
    fake.fail_set = True
    assert await cache.get(LeaderboardPeriod.WEEK, 10, start) is None
    await cache.set(LeaderboardPeriod.WEEK, 10, start, rows, 60)


async def test_cache_skips_non_positive_ttl() -> None:
    cache, fake = _cache_with_fake()
    start = datetime(2026, 3, 1, 16, tzinfo=UTC)
    await cache.set(LeaderboardPeriod.WEEK, 10, start, [], 0)
    assert fake.data == {}


async def test_cache_degrades_when_client_factory_fails() -> None:
    def _bad_factory() -> FakeAsyncRedis:
        raise ValueError("invalid redis url")

    cache: RedisLeaderboardCache = RedisLeaderboardCache(_bad_factory)  # type: ignore[arg-type,return-value]
    start = datetime(2026, 3, 1, 16, tzinfo=UTC)

    assert await cache.get(LeaderboardPeriod.WEEK, 10, start) is None
