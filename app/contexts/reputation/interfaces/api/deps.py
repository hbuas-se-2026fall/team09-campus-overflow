"""reputation 组合根：仓储适配器的唯一装配处（与 qa/identity 同模式）。

interfaces 层只在本文件 import infrastructure；路由参数类型是 domain 端口
（Protocol），换存储实现只改本文件。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.contexts.reputation.application.ports import LeaderboardCache
from app.contexts.reputation.domain.repository import ReputationLedgerRepository
from app.contexts.reputation.infrastructure.leaderboard_cache import RedisLeaderboardCache
from app.contexts.reputation.infrastructure.repository import (
    SqlAlchemyReputationLedgerRepository,
)
from app.platform.http.deps import SessionDep
from app.shared.redis import get_redis

_leaderboard_cache = RedisLeaderboardCache(get_redis)


def get_reputation_ledger_repository(session: SessionDep) -> ReputationLedgerRepository:
    return SqlAlchemyReputationLedgerRepository(session)


def get_leaderboard_cache() -> LeaderboardCache:
    return _leaderboard_cache


ReputationLedgerRepo = Annotated[
    ReputationLedgerRepository, Depends(get_reputation_ledger_repository)
]
LeaderboardCacheDep = Annotated[LeaderboardCache, Depends(get_leaderboard_cache)]
