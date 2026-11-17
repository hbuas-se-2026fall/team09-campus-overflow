"""查询当前用户积分余额与流水用例（F07 闭环）。

教师首次访问惰性开户并发放初始 100 积分（与发起悬赏同源，幂等）；
学生只读既有账户与流水，不发放教师初始额度。
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.contexts.qa.domain.bounty import PointsEntry
from app.contexts.qa.domain.repository import PointsRepository


@dataclass(frozen=True, slots=True)
class MyPointsView:
    balance: int
    entries: list[PointsEntry]


class GetMyPointsUseCase:
    def __init__(self, points_repository: PointsRepository) -> None:
        self._points = points_repository

    async def execute(self, user_id: UUID, role: str) -> MyPointsView:
        if role == "teacher":
            balance = await self._points.ensure_teacher_account(user_id)
        else:
            balance = await self._points.balance(user_id)
        entries = await self._points.list_entries(user_id)
        return MyPointsView(balance=balance, entries=entries)
