"""qa 仓储 SQL 表达式纯函数单测（F02）：不连库，CI 直接运行。"""

from __future__ import annotations

import pytest

from app.contexts.qa.infrastructure.sql_expressions import escape_like


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("React Hooks", "React Hooks"),  # 普通文本原样保留
        ("", ""),
        ("100%", "100\\%"),  # % 字面转义
        ("a_b", "a\\_b"),  # _ 字面转义
        ("a\\b", "a\\\\b"),  # 反斜杠自身翻倍
        ("50%_off\\", "50\\%\\_off\\\\"),  # 三类通配符混合
        ("\\%", "\\\\\\%"),  # 顺序守卫：先转反斜杠，再转 %，不得二次转义
        ("\\_", "\\\\\\_"),  # 顺序守卫：_ 同理
    ],
)
def test_escape_like_matches_literal(raw: str, expected: str) -> None:
    assert escape_like(raw) == expected
