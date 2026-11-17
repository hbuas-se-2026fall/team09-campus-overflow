"""用户徽章用例单测（F06）：统计聚合与视图组装，不连库，进 CI。"""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

from app.contexts.qa.application.get_user_badges_use_case import GetUserBadgesUseCase


class FakeActivityRepository:
    def __init__(
        self, stats: tuple[int, int], days: list[date] | None = None
    ) -> None:
        self.stats = stats
        self.days = days or []

    async def answer_stats(self, user_id: object) -> tuple[int, int]:
        return self.stats

    async def active_dates(self, user_id: object) -> list[date]:
        return self.days


async def test_badges_view_assembles_stats_and_rules() -> None:
    base = date(2026, 3, 1)
    repo = FakeActivityRepository(
        stats=(5, 3), days=[base, base + timedelta(days=1), base + timedelta(days=2)]
    )
    view = await GetUserBadgesUseCase(repo).execute(uuid4())

    assert view.answer_count == 5
    assert view.accepted_count == 3
    assert view.acceptance_rate == 0.6
    assert view.longest_streak_days == 3
    codes = [b.code for b in view.badges]
    assert "answers_5" in codes
    assert "acceptance_50" in codes
    assert "streak_3" in codes
    assert "acceptance_70" not in codes


async def test_badges_no_activity_returns_empty() -> None:
    repo = FakeActivityRepository(stats=(0, 0), days=[])
    view = await GetUserBadgesUseCase(repo).execute(uuid4())
    assert view.answer_count == 0
    assert view.acceptance_rate == 0.0
    assert view.longest_streak_days == 0
    assert view.badges == []
