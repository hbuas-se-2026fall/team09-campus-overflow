"""qa 仓储共用 SQL 表达式：净票数口径单源（问题排序与回答装配共用）。"""

from __future__ import annotations

from sqlalchemy import ColumnElement, case, func

from app.contexts.qa.domain.vote import VoteDirection
from app.contexts.qa.infrastructure.models import VoteModel


def escape_like(value: str) -> str:
    r"""转义 LIKE/ILIKE 通配符，使用户输入按字面匹配（F02）。

    顺序必须严格 反斜杠 → ``%`` → ``_``：若先替换 ``%``/``_``，
    后续的反斜杠替换会把刚插入的转义符再转义一次，导致匹配语义错乱。
    与 SQL 侧的 ``escape="\\"`` 成对使用。
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def net_votes_expr() -> ColumnElement[int]:
    """净票数表达式（v3 裁定 #1：up − down）：赞成 +1、反对 −1 求和，无票为 0。"""
    return func.coalesce(
        func.sum(case((VoteModel.direction == VoteDirection.UP.value, 1), else_=-1)),
        0,
    )
