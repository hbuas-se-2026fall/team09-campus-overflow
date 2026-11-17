"""ReputationLedger 持久化端口：domain 定义接口，infrastructure 实现（与 qa/identity 同口径）。"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.contexts.reputation.domain.leaderboard import LeaderboardRow
from app.contexts.reputation.domain.ledger import LedgerEntry


class ReputationLedgerRepository(Protocol):
    """声誉账本持久化端口（US-REP01/REP02）。"""

    async def append_if_absent(self, user_id: UUID, entry: LedgerEntry) -> bool:
        """追加流水行；同 (source, event_id) 已存在时不写并返回 False（幂等）。

        库级兜底：唯一索引 (source, event_id) + ON CONFLICT DO NOTHING——
        并发双投递也恰落一行（返回 True 恰一次）。
        """
        ...

    async def total(self, user_id: UUID) -> int:
        """账面声誉值（流水累加；无流水返回 0）。"""
        ...

    async def entries_desc(self, user_id: UUID) -> list[LedgerEntry]:
        """流水按 occurred_at 倒序（Gherkin 功能域 11 场景 3）。"""
        ...

    async def list_top(
        self, start: datetime, end: datetime, limit: int
    ) -> list[LeaderboardRow]:
        """排行榜（F05）：[start, end) 内按用户汇总净得分，降序取前 limit。

        名次为 competition ranking（同分同名次，D9）；净得分含负（D8）。
        """
        ...
