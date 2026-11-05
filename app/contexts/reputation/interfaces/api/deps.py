"""reputation 组合根：仓储适配器的唯一装配处（与 qa/identity 同模式）。

interfaces 层只在本文件 import infrastructure；路由参数类型是 domain 端口
（Protocol），换存储实现只改本文件。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.contexts.reputation.domain.repository import ReputationLedgerRepository
from app.contexts.reputation.infrastructure.repository import (
    SqlAlchemyReputationLedgerRepository,
)
from app.platform.http.deps import SessionDep


def get_reputation_ledger_repository(session: SessionDep) -> ReputationLedgerRepository:
    return SqlAlchemyReputationLedgerRepository(session)


ReputationLedgerRepo = Annotated[
    ReputationLedgerRepository, Depends(get_reputation_ledger_repository)
]
