"""排行榜接口集成测试（F05）：公开访问、Top N、同分同名次、边界 422。

用大分值种子确保不受历史测试流水干扰；窗口外种子用 1990 年隔离。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from redis.exceptions import RedisError
from sqlalchemy import delete

from app.contexts.reputation.domain.ledger import LedgerEntry, LedgerSource
from app.contexts.reputation.infrastructure.leaderboard_cache import RedisLeaderboardCache
from app.contexts.reputation.infrastructure.models import ReputationLedgerModel
from app.contexts.reputation.infrastructure.repository import (
    SqlAlchemyReputationLedgerRepository,
)
from app.contexts.reputation.interfaces.api.deps import get_leaderboard_cache
from app.main import create_app
from app.shared.engine import session_factory
from app.shared.redis import get_redis

pytestmark = pytest.mark.integration

BASE_URL = "http://test"


async def _clear_leaderboard_cache() -> None:
    redis = get_redis()
    keys = [key async for key in redis.scan_iter(match="v1:leaderboard:*")]
    if keys:
        await redis.delete(*keys)


@pytest.fixture
async def client(redis_cleanup: None) -> httpx.AsyncClient:
    await _clear_leaderboard_cache()
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as c:
        yield c
    await _clear_leaderboard_cache()


async def _register(client: httpx.AsyncClient) -> str:
    payload: dict[str, Any] = {
        "role": "student",
        "email": f"{uuid.uuid4()}@stu.edu.cn",
        "password": "Passw0rd8",
        "student_id": str(uuid.uuid4().int)[:10],
    }
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def _seed_ledger(user_id: str, delta: int, occurred_at: datetime) -> uuid.UUID:
    event_id = uuid.uuid4()
    async with session_factory() as session:
        repo = SqlAlchemyReputationLedgerRepository(session)
        await repo.append_if_absent(
            uuid.UUID(user_id),
            LedgerEntry(
                source=LedgerSource.VOTE,
                event_id=event_id,
                delta=delta,
                reason="排行榜集成测试",
                occurred_at=occurred_at,
            ),
        )
        await session.commit()
    return event_id


async def _cleanup_ledgers(event_ids: list[uuid.UUID]) -> None:
    async with session_factory() as session:
        await session.execute(
            delete(ReputationLedgerModel).where(
                ReputationLedgerModel.event_id.in_(event_ids)
            )
        )
        await session.commit()


async def test_leaderboard_public_top_and_competition_rank(
    client: httpx.AsyncClient,
) -> None:
    high = await _register(client)
    tie_a = await _register(client)
    tie_b = await _register(client)
    now = datetime.now(UTC)
    # 单调基座：时间戳恒增，本轮分值必然压过历史轮遗留；finally 再清掉本轮种子，
    # 防止同秒双跑等极端情形（457 复跑失败的根因是随机基座不保证单调）。
    base_score = 10_000_000 + int(now.timestamp())
    event_ids: list[uuid.UUID] = []
    try:
        event_ids.append(await _seed_ledger(high, base_score + 2, now))
        event_ids.append(await _seed_ledger(tie_a, base_score + 1, now))
        event_ids.append(await _seed_ledger(tie_b, base_score + 1, now))

        resp = await client.get(
            "/api/v1/leaderboard", params={"period": "week", "limit": 100}
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["period"] == "week"
        assert data["period_start"] < data["period_end"]
        entries = data["entries"]
        by_user = {e["user_id"]: e for e in entries}
        assert by_user[high]["rank"] == 1
        assert by_user[high]["score"] == base_score + 2
        assert by_user[tie_a]["rank"] == by_user[tie_b]["rank"] == 2
        assert entries[0]["user_id"] == high

        limited = await client.get(
            "/api/v1/leaderboard", params={"period": "week", "limit": 1}
        )
        assert limited.status_code == 200, limited.text
        assert [e["user_id"] for e in limited.json()["entries"]] == [high]
    finally:
        await _cleanup_ledgers(event_ids)


async def test_leaderboard_excludes_outside_period(
    client: httpx.AsyncClient,
) -> None:
    user_id = await _register(client)
    await _seed_ledger(user_id, 2_000_000, datetime(1990, 1, 1, tzinfo=UTC))

    resp = await client.get(
        "/api/v1/leaderboard", params={"period": "week", "limit": 100}
    )
    assert resp.status_code == 200, resp.text
    assert user_id not in {e["user_id"] for e in resp.json()["entries"]}


async def test_leaderboard_invalid_params_return_422(
    client: httpx.AsyncClient,
) -> None:
    for params in ({"period": "bogus"}, {"limit": 0}, {"limit": 101}):
        resp = await client.get("/api/v1/leaderboard", params=params)
        assert resp.status_code == 422, (params, resp.text)


async def test_leaderboard_redis_cache_hit_within_ttl(
    client: httpx.AsyncClient,
) -> None:
    user_id = await _register(client)
    now = datetime.now(UTC)
    base_score = 10_000_000 + int(now.timestamp())
    event_id = await _seed_ledger(user_id, base_score + 5, now)
    try:
        first = await client.get(
            "/api/v1/leaderboard", params={"period": "week", "limit": 100}
        )
        assert first.status_code == 200, first.text
        assert user_id in {e["user_id"] for e in first.json()["entries"]}

        # 删除种子流水后仍在 TTL 内再次请求：若命中缓存，仍返回首轮快照
        await _cleanup_ledgers([event_id])
        second = await client.get(
            "/api/v1/leaderboard", params={"period": "week", "limit": 100}
        )
        assert second.status_code == 200, second.text
        assert second.json() == first.json()
    finally:
        await _cleanup_ledgers([event_id])


async def test_leaderboard_degrades_to_db_when_redis_unavailable(
    redis_cleanup: None,
) -> None:
    class _BrokenRedis:
        async def get(self, key: str) -> str | None:
            raise RedisError("simulated outage")

        async def set(self, key: str, value: str, *, ex: int) -> None:
            raise RedisError("simulated outage")

    app = create_app()
    app.dependency_overrides[get_leaderboard_cache] = lambda: RedisLeaderboardCache(
        lambda: _BrokenRedis()  # type: ignore[arg-type,return-value]
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as broken_client:
        user_id = await _register(broken_client)
        now = datetime.now(UTC)
        base_score = 10_000_000 + int(now.timestamp())
        event_id = await _seed_ledger(user_id, base_score + 9, now)
        try:
            resp = await broken_client.get(
                "/api/v1/leaderboard", params={"period": "week", "limit": 100}
            )
            assert resp.status_code == 200, resp.text
            assert user_id in {e["user_id"] for e in resp.json()["entries"]}
        finally:
            await _cleanup_ledgers([event_id])
