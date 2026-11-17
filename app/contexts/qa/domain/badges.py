"""徽章规则（F06）：回答数 / 采纳率 / 历史最长连续活跃天数（D11/D14）。

阈值常量为唯一出处；首版实时计算，不物化。
- 回答数：5/20/50（铜/银/金）
- 采纳率：回答数 ≥5 才评估，50%/70%/90%（铜/银/金）
- 连续活跃：历史最长连续天数 3/7/30（铜/银/金）——徽章是成就记录，不用"当前连续"
- 活跃 = 发帖/回答/评论/投票四类内容行为，不含登录（D11）
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum


class BadgeKind(StrEnum):
    ANSWER_COUNT = "answer_count"
    ACCEPTANCE_RATE = "acceptance_rate"
    ACTIVE_STREAK = "active_streak"


class BadgeTier(StrEnum):
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"


@dataclass(frozen=True, slots=True)
class Badge:
    """一枚徽章：稳定 code + 类别/等级/阈值。"""

    code: str
    kind: BadgeKind
    tier: BadgeTier
    threshold: float


_ANSWER_TIERS: tuple[tuple[int, BadgeTier], ...] = (
    (5, BadgeTier.BRONZE),
    (20, BadgeTier.SILVER),
    (50, BadgeTier.GOLD),
)
_ACCEPTANCE_MIN_ANSWERS = 5
_ACCEPTANCE_TIERS: tuple[tuple[float, BadgeTier], ...] = (
    (0.5, BadgeTier.BRONZE),
    (0.7, BadgeTier.SILVER),
    (0.9, BadgeTier.GOLD),
)
_STREAK_TIERS: tuple[tuple[int, BadgeTier], ...] = (
    (3, BadgeTier.BRONZE),
    (7, BadgeTier.SILVER),
    (30, BadgeTier.GOLD),
)


def longest_active_streak(days: Iterable[date]) -> int:
    """历史最长连续活跃天数（去重、跨月/跨年按自然日连续）。"""
    ordered = sorted(set(days))
    best = current = 0
    previous: date | None = None
    for day in ordered:
        if previous is not None and day - previous == timedelta(days=1):
            current += 1
        else:
            current = 1
        best = max(best, current)
        previous = day
    return best


def evaluate_badges(
    *, answer_count: int, accepted_count: int, longest_streak: int
) -> list[Badge]:
    """按阈值生成徽章列表（同一类别可同时命中多档）。"""
    badges: list[Badge] = []
    for threshold, tier in _ANSWER_TIERS:
        if answer_count >= threshold:
            badges.append(
                Badge(
                    code=f"answers_{threshold}",
                    kind=BadgeKind.ANSWER_COUNT,
                    tier=tier,
                    threshold=float(threshold),
                )
            )
    if answer_count >= _ACCEPTANCE_MIN_ANSWERS:
        rate = accepted_count / answer_count
        for rate_threshold, tier in _ACCEPTANCE_TIERS:
            if rate >= rate_threshold:
                badges.append(
                    Badge(
                        code=f"acceptance_{int(rate_threshold * 100)}",
                        kind=BadgeKind.ACCEPTANCE_RATE,
                        tier=tier,
                        threshold=rate_threshold,
                    )
                )
    for threshold, tier in _STREAK_TIERS:
        if longest_streak >= threshold:
            badges.append(
                Badge(
                    code=f"streak_{threshold}",
                    kind=BadgeKind.ACTIVE_STREAK,
                    tier=tier,
                    threshold=float(threshold),
                )
            )
    return badges
