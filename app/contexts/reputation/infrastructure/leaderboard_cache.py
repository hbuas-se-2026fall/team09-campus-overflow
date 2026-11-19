"""排行榜 Redis 热榜缓存适配器（F08）。

Key 格式、版本前缀与 JSON 序列化均收口于本模块：
- Key：`v1:leaderboard:{period}:{limit}:{start_utc_iso}`
- 读取区分未命中/异常降级（返回 None）与已缓存空榜（返回 []）
- RedisError / OSError / 脏 JSON 一律记 warning 并降级为 None，不阻断直查数据库
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from redis.exceptions import RedisError

from app.contexts.reputation.domain.leaderboard import LeaderboardPeriod, LeaderboardRow

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)


def _cache_key(period: LeaderboardPeriod, limit: int, start: datetime) -> str:
    start_iso = start.astimezone(UTC).isoformat()
    return f"v1:leaderboard:{period.value}:{limit}:{start_iso}"


def _serialize_rows(rows: list[LeaderboardRow]) -> str:
    payload = [
        {"user_id": str(row.user_id), "score": row.score, "rank": row.rank}
        for row in rows
    ]
    return json.dumps(payload, separators=(",", ":"))


class _CorruptCachePayloadError(Exception):
    """内部载荷结构非法信号，触发缓存降级。"""


def _deserialize_rows(raw: str) -> list[LeaderboardRow]:
    data: Any = json.loads(raw)
    if not isinstance(data, list):
        raise _CorruptCachePayloadError("leaderboard cache payload must be a list")
    rows: list[LeaderboardRow] = []
    for item in data:
        if not isinstance(item, dict):
            raise _CorruptCachePayloadError("leaderboard cache item must be a dict")
        score = item["score"]
        rank = item["rank"]
        if (
            not isinstance(score, int)
            or isinstance(score, bool)
            or not isinstance(rank, int)
            or isinstance(rank, bool)
        ):
            raise _CorruptCachePayloadError("leaderboard score/rank must be integers")
        rows.append(
            LeaderboardRow(
                user_id=UUID(str(item["user_id"])),
                score=score,
                rank=rank,
            )
        )
    return rows


class RedisLeaderboardCache:
    """LeaderboardCache 端口的 Redis 实现（支持注入客户端工厂便于测试与隔离）。"""

    def __init__(self, client_factory: Callable[[], Redis]) -> None:
        self._client_factory = client_factory

    async def get(
        self,
        period: LeaderboardPeriod,
        limit: int,
        start: datetime,
    ) -> list[LeaderboardRow] | None:
        key = _cache_key(period, limit, start)
        try:
            client = self._client_factory()
            raw = await client.get(key)
        except (RedisError, OSError, ValueError, TypeError):
            logger.warning("排行榜缓存读取失败，降级直查数据库: key=%s", key, exc_info=True)
            return None
        if raw is None:
            return None
        try:
            return _deserialize_rows(str(raw))
        except (
            _CorruptCachePayloadError,
            json.JSONDecodeError,
            KeyError,
            TypeError,
            ValueError,
        ):
            logger.warning("排行榜缓存载荷损坏，降级直查数据库: key=%s", key, exc_info=True)
            return None

    async def set(
        self,
        period: LeaderboardPeriod,
        limit: int,
        start: datetime,
        rows: list[LeaderboardRow],
        ttl_seconds: int,
    ) -> None:
        if ttl_seconds <= 0:
            return
        key = _cache_key(period, limit, start)
        try:
            await self._client_factory().set(key, _serialize_rows(rows), ex=ttl_seconds)
        except (RedisError, OSError, TypeError, ValueError):
            logger.warning("排行榜缓存写入失败（已忽略）: key=%s", key, exc_info=True)
