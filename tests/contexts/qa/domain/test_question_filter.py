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


def test_too_many_distinct_tag_keys_rejected() -> None:
    """评审加固：AND 语义下 >5 个不同 key 必然空结果，域内直接 422 拒绝。"""
    with pytest.raises(DomainValidationError, match="至多 5 个"):
        QuestionFilter(tags=("alpha", "beta", "gamma", "delta", "epsilon", "zeta"))


def test_duplicate_tags_do_not_count_toward_cap() -> None:
    """上限按去重后的 key 计：重复传参不影响判定（D3a 语义）。"""
    filters = QuestionFilter(
        tags=("React", "react", "React", "TypeScript", "React", "PostgreSQL")
    )
    assert filters.tag_keys == ("react", "typescript", "postgresql")


def test_exactly_five_distinct_tags_allowed() -> None:
    """边界：恰好 5 个不同 key 放行（钉住 `>` 而非 `>=`，同时守住常量被误改）。"""
    filters = QuestionFilter(
        tags=("React", "TypeScript", "PostgreSQL", "Redis", "Docker")
    )
    assert filters.tag_keys == (
        "react",
        "typescript",
        "postgresql",
        "redis",
        "docker",
    )


def test_q_defaults_to_none() -> None:
    """F02：不传 q 时保持 None，infra 不会拼出 LIKE 条件。"""
    assert QuestionFilter().q is None


def test_q_is_stripped_and_written_back() -> None:
    """F02 小注 1：规范化值必须回写，否则 infra 会拿带首尾空白的 q 去拼 %q%。"""
    filters = QuestionFilter(q="  React Hooks  ")
    assert filters.q == "React Hooks"


@pytest.mark.parametrize("raw", ["", "   ", "\t\n\r "])
def test_blank_q_normalized_to_none(raw: str) -> None:
    """F02：空串/纯空白等价于不传（先 strip，故纯空白不会被当成控制字符拒绝）。"""
    assert QuestionFilter(q=raw).q is None


def test_q_with_nul_rejected() -> None:
    with pytest.raises(DomainValidationError, match="控制字符"):
        QuestionFilter(q="React\x00Hooks")


def test_q_with_lone_surrogate_rejected() -> None:
    """lone surrogate 无法编码 UTF-8：放在 domain 单测（API 层发不出这种请求）。"""
    with pytest.raises(DomainValidationError, match="代理字符"):
        QuestionFilter(q="React\ud800Hooks")


@pytest.mark.parametrize("raw", ["React\tHooks", "React\nHooks", "React\rHooks"])
def test_q_with_tab_or_newline_rejected(raw: str) -> None:
    """D7：检索词单行化，制表/换行/回车在域内拒绝（不改 shared 签名）。"""
    with pytest.raises(DomainValidationError, match="制表符或换行符"):
        QuestionFilter(q=raw)


def test_q_at_max_length_allowed() -> None:
    """D5 边界：恰好 100 字放行，且回写值长度不变。"""
    filters = QuestionFilter(q="a" * 100)
    assert filters.q == "a" * 100
    assert len(filters.q) == 100


def test_q_over_max_length_rejected() -> None:
    """D5：超 1 字即 422，防止超长 LIKE 参数进 SQL。"""
    with pytest.raises(DomainValidationError, match="至多 100 字"):
        QuestionFilter(q="a" * 101)


def test_q_coexists_with_other_filters() -> None:
    """F02 与 F01 组合：q 不影响其它条件的归一与保留。"""
    moment = datetime(2026, 1, 1, tzinfo=UTC)
    filters = QuestionFilter(
        tags=("React",),
        status=QuestionStatus.OPEN,
        created_from=moment,
        q="  SQLAlchemy  ",
    )
    assert filters.q == "SQLAlchemy"
    assert filters.tag_keys == ("react",)
    assert filters.status is QuestionStatus.OPEN
    assert filters.created_from == moment


