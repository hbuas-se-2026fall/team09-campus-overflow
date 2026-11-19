"""徽章规则单测（F06）：阈值边界、连续天数、采纳率分母，不连库，进 CI。"""

from __future__ import annotations

from datetime import date, timedelta

from app.contexts.qa.domain.badges import (
    BadgeKind,
    BadgeTier,
    evaluate_badges,
    longest_active_streak,
)


def test_longest_streak_empty_is_zero() -> None:
    assert longest_active_streak([]) == 0


def test_longest_streak_returns_longest_run() -> None:
    base = date(2026, 1, 1)
    days = [base, base + timedelta(days=1), base + timedelta(days=2), base + timedelta(days=5)]
    assert longest_active_streak(days) == 3


def test_longest_streak_dedupes_and_handles_gaps() -> None:
    base = date(2026, 1, 1)
    days = [base, base, base + timedelta(days=2), base + timedelta(days=3)]
    assert longest_active_streak(days) == 2


def test_answer_count_badges_boundaries() -> None:
    def codes(count: int) -> list[str]:
        return [
            b.code
            for b in evaluate_badges(
                answer_count=count, accepted_count=0, longest_streak=0
            )
            if b.kind is BadgeKind.ANSWER_COUNT
        ]

    assert codes(4) == []
    assert codes(5) == ["answers_5"]
    assert codes(20) == ["answers_5", "answers_20"]
    assert codes(50) == ["answers_5", "answers_20", "answers_50"]


def test_acceptance_rate_requires_min_answers() -> None:
    """回答数 <5 不评估采纳率（防 1/1 满分套徽章）；分母 0 同样不评估。"""
    assert [
        b
        for b in evaluate_badges(
            answer_count=4, accepted_count=4, longest_streak=0
        )
        if b.kind is BadgeKind.ACCEPTANCE_RATE
    ] == []
    assert [
        b
        for b in evaluate_badges(
            answer_count=0, accepted_count=0, longest_streak=0
        )
        if b.kind is BadgeKind.ACCEPTANCE_RATE
    ] == []


def test_acceptance_rate_thresholds() -> None:
    def tiers(accepted: int) -> list[BadgeTier]:
        return [
            b.tier
            for b in evaluate_badges(
                answer_count=10, accepted_count=accepted, longest_streak=0
            )
            if b.kind is BadgeKind.ACCEPTANCE_RATE
        ]

    assert tiers(4) == []  # 40%
    assert tiers(5) == [BadgeTier.BRONZE]  # 50%
    assert tiers(7) == [BadgeTier.BRONZE, BadgeTier.SILVER]  # 70%
    assert tiers(9) == [BadgeTier.BRONZE, BadgeTier.SILVER, BadgeTier.GOLD]  # 90%


def test_streak_badges_boundaries() -> None:
    def codes(days: int) -> list[str]:
        return [
            b.code
            for b in evaluate_badges(
                answer_count=0, accepted_count=0, longest_streak=days
            )
            if b.kind is BadgeKind.ACTIVE_STREAK
        ]

    assert codes(2) == []
    assert codes(3) == ["streak_3"]
    assert codes(7) == ["streak_3", "streak_7"]
    assert codes(30) == ["streak_3", "streak_7", "streak_30"]
