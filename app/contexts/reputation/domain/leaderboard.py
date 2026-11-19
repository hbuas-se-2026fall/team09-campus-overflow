"""排行榜周期口径（F05）：周/月/学期区间与名次（D8–D10 裁定）。

边界统一按 Asia/Shanghai 计算，再转 UTC 参与 timestamptz 查询：
- 周：周一 00:00 起，下周一 00:00 止（左闭右开）
- 月：当月 1 日 00:00 起，次月 1 日 00:00 止
- 学期：春季 3/1–8/1；秋季 9/1–次年 2/1；2 月归上一秋季、8 月归当年春季
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, timezone
from enum import StrEnum
from uuid import UUID

_SHANGHAI = timezone(timedelta(hours=8), name="Asia/Shanghai")


class LeaderboardPeriod(StrEnum):
    """榜单周期（2.3.3：周/月/学期）。"""

    WEEK = "week"
    MONTH = "month"
    SEMESTER = "semester"


@dataclass(frozen=True, slots=True)
class LeaderboardRow:
    """单条榜单行：用户、期间净得分、名次（同分同名次，D8/D9）。"""

    user_id: UUID
    score: int
    rank: int


def _to_utc(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=_SHANGHAI).astimezone(UTC)


def resolve_period_range(
    period: LeaderboardPeriod, *, now: datetime | None = None
) -> tuple[datetime, datetime]:
    """返回 [start, end) 的 UTC 区间（D10 学期边界见模块 docstring）。"""
    local = (now or datetime.now(UTC)).astimezone(_SHANGHAI)
    if period is LeaderboardPeriod.WEEK:
        start_day = local.date() - timedelta(days=local.weekday())
        end_day = start_day + timedelta(days=7)
    elif period is LeaderboardPeriod.MONTH:
        start_day = local.date().replace(day=1)
        end_day = (
            date(start_day.year + 1, 1, 1)
            if start_day.month == 12
            else date(start_day.year, start_day.month + 1, 1)
        )
    else:
        year, month = local.year, local.month
        if 3 <= month <= 7:
            start_day, end_day = date(year, 3, 1), date(year, 8, 1)
        elif 9 <= month <= 12:
            start_day, end_day = date(year, 9, 1), date(year + 1, 2, 1)
        elif month in (1, 2):
            # 1 月仍属上一秋季；2 月（寒假）取最近学期 = 上一秋季（D10）
            start_day, end_day = date(year - 1, 9, 1), date(year, 2, 1)
        else:
            # 8 月（暑假）取最近学期 = 当年春季（D10）
            start_day, end_day = date(year, 3, 1), date(year, 8, 1)
    return _to_utc(start_day), _to_utc(end_day)
