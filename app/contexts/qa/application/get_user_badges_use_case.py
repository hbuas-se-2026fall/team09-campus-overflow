"""用户徽章用例（F06，只读）：回答数/采纳数 + 活跃日 → 徽章规则。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.contexts.qa.domain.badges import (
    Badge,
    evaluate_badges,
    longest_active_streak,
)
from app.contexts.qa.domain.repository import UserActivityRepository


@dataclass(frozen=True, slots=True)
class UserBadgesView:
    user_id: UUID
    answer_count: int
    accepted_count: int
    acceptance_rate: float
    longest_streak_days: int
    badges: list[Badge]


class GetUserBadgesUseCase:
    """实时计算徽章（首版不物化）；用户存在性由路由层校验。"""

    def __init__(self, repository: UserActivityRepository) -> None:
        self._repository = repository

    async def execute(self, user_id: UUID) -> UserBadgesView:
        answer_count, accepted_count = await self._repository.answer_stats(user_id)
        days = await self._repository.active_dates(user_id)
        streak = longest_active_streak(days)
        badges = evaluate_badges(
            answer_count=answer_count,
            accepted_count=accepted_count,
            longest_streak=streak,
        )
        rate = accepted_count / answer_count if answer_count else 0.0
        return UserBadgesView(
            user_id=user_id,
            answer_count=answer_count,
            accepted_count=accepted_count,
            acceptance_rate=rate,
            longest_streak_days=streak,
            badges=badges,
        )
