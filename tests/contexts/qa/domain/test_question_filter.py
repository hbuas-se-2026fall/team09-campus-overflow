"""QuestionFilter 领域单测（F01，D2/D3/D4 裁定）：校验与归一，不连库、进 CI。"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.contexts.qa.domain.question import QuestionStatus
from app.contexts.qa.domain.repository import QuestionFilter
from app.shared.errors import DomainValidationError


def test_empty_filter_matches_legacy_behaviour() -> None:
    """D1：不传任何条件 = 全部，等价于 F01 之前的列表行为。"""
    filters = QuestionFilter()
    assert filters.tag_keys == ()
    assert filters.status is None
    assert filters.created_from is None
    assert filters.created_to is None


def test_tags_normalized_to_keys_and_deduped_by_key() -> None:
    """D4：显示名经 Tag 规范化后取 key；同名（大小写/词尾 sigma）去重。"""
    filters = QuestionFilter(tags=("React", "react", "Σ", "σ"))
    assert filters.tag_keys == ("react", "σ")


def test_tag_display_name_is_stripped() -> None:
    filters = QuestionFilter(tags=("  PostgreSQL  ",))
    assert filters.tag_keys == ("postgresql",)


def test_naive_created_from_rejected() -> None:
    """D2：timestamptz 比较必须无歧义——naive datetime 一律 422。"""
    with pytest.raises(DomainValidationError, match="时区"):
        QuestionFilter(created_from=datetime(2026, 1, 1))


def test_naive_created_to_rejected() -> None:
    with pytest.raises(DomainValidationError, match="时区"):
        QuestionFilter(created_to=datetime(2026, 1, 1))


def test_reverse_range_rejected() -> None:
    with pytest.raises(DomainValidationError, match="不能晚于"):
        QuestionFilter(
            created_from=datetime(2026, 1, 2, tzinfo=UTC),
            created_to=datetime(2026, 1, 1, tzinfo=UTC),
        )


def test_equal_boundaries_are_allowed() -> None:
    """闭区间 [t, t] 合法（单点窗口）。"""
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    filters = QuestionFilter(created_from=moment, created_to=moment)
    assert filters.created_from == moment
    assert filters.created_to == moment


def test_empty_tag_rejected() -> None:
    with pytest.raises(DomainValidationError, match="标签需"):
        QuestionFilter(tags=("   ",))


def test_illegal_tag_character_rejected() -> None:
    with pytest.raises(DomainValidationError, match="不支持的字符"):
        QuestionFilter(tags=("React;DROP",))


def test_status_is_preserved() -> None:
    filters = QuestionFilter(status=QuestionStatus.CLOSED)
    assert filters.status is QuestionStatus.CLOSED
