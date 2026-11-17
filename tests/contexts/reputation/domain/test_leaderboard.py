"""排行榜周期边界单测（F05/D10）：固定时刻，不连库，进 CI。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.contexts.reputation.domain.leaderboard import (
    LeaderboardPeriod,
    resolve_period_range,
)

SH = timezone(timedelta(hours=8), name="Asia/Shanghai")


def _at(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=SH)


def _utc(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=SH).astimezone(UTC)


@pytest.mark.parametrize(
    ("now", "expected_start", "expected_end"),
    [
        # 周三 → 本周一 00:00 至下周一 00:00
        (_at(2026, 3, 4, 12), _utc(2026, 3, 2), _utc(2026, 3, 9)),
        # 周一 00:00 属于新一周起点（左闭）
        (_at(2026, 3, 2), _utc(2026, 3, 2), _utc(2026, 3, 9)),
        # 周日 23:59 仍属本周
        (_at(2026, 3, 8, 23), _utc(2026, 3, 2), _utc(2026, 3, 9)),
    ],
)
def test_week_boundaries(
    now: datetime, expected_start: datetime, expected_end: datetime
) -> None:
    assert resolve_period_range(LeaderboardPeriod.WEEK, now=now) == (
        expected_start,
        expected_end,
    )


@pytest.mark.parametrize(
    ("now", "expected_start", "expected_end"),
    [
        (_at(2026, 3, 15), _utc(2026, 3, 1), _utc(2026, 4, 1)),
        (_at(2026, 3, 31, 23), _utc(2026, 3, 1), _utc(2026, 4, 1)),
        # 12 月跨年
        (_at(2026, 12, 31), _utc(2026, 12, 1), _utc(2027, 1, 1)),
    ],
)
def test_month_boundaries(
    now: datetime, expected_start: datetime, expected_end: datetime
) -> None:
    assert resolve_period_range(LeaderboardPeriod.MONTH, now=now) == (
        expected_start,
        expected_end,
    )


@pytest.mark.parametrize(
    ("now", "expected_start", "expected_end"),
    [
        # 春季：3/1–8/1
        (_at(2026, 3, 1), _utc(2026, 3, 1), _utc(2026, 8, 1)),
        (_at(2026, 7, 31, 23), _utc(2026, 3, 1), _utc(2026, 8, 1)),
        # 8 月（暑假）→ 当年春季（D10）
        (_at(2026, 8, 15), _utc(2026, 3, 1), _utc(2026, 8, 1)),
        # 秋季：9/1–次年 2/1
        (_at(2026, 9, 1), _utc(2026, 9, 1), _utc(2027, 2, 1)),
        (_at(2026, 12, 31), _utc(2026, 9, 1), _utc(2027, 2, 1)),
        # 1 月仍属上一秋季
        (_at(2026, 1, 15), _utc(2025, 9, 1), _utc(2026, 2, 1)),
        # 2 月（寒假）→ 上一秋季（D10）
        (_at(2026, 2, 15), _utc(2025, 9, 1), _utc(2026, 2, 1)),
    ],
)
def test_semester_boundaries(
    now: datetime, expected_start: datetime, expected_end: datetime
) -> None:
    assert resolve_period_range(LeaderboardPeriod.SEMESTER, now=now) == (
        expected_start,
        expected_end,
    )
