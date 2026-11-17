"""教师悬赏领域（F07）：积分账本与悬赏状态机（D12/D13）。

- 积分与声誉分离：本模块只服务可消费积分，不读写 reputation_ledgers。
- 教师首次访问惰性开户并发放初始积分；授予流水以 (source='grant', event_id=user_id) 幂等。
- 悬赏状态：open → settled（采纳结算）/ refunded（关闭未采纳退款），条件 UPDATE 保证只发生一次。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

# 教师初始积分额度（D12：首版不做发放端点）
INITIAL_TEACHER_POINTS = 100


class BountyStatus(StrEnum):
    OPEN = "open"
    SETTLED = "settled"
    REFUNDED = "refunded"


@dataclass(frozen=True, slots=True)
class Bounty:
    id: UUID
    question_id: UUID
    teacher_id: UUID
    amount: int
    status: BountyStatus
    created_at: datetime
    settled_at: datetime | None


@dataclass(frozen=True, slots=True)
class PointsEntry:
    """积分流水行（只追加）；(source, event_id) 唯一保证同一事件恰记一次。"""

    source: str
    event_id: UUID
    delta: int
    reason: str
    occurred_at: datetime
