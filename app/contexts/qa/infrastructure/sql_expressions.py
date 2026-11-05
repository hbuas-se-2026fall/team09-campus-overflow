"""qa 仓储共用 SQL 表达式：净票数口径单源（问题排序与回答装配共用）。"""

from __future__ import annotations

from sqlalchemy import ColumnElement, case, func

from app.contexts.qa.domain.vote import VoteDirection
from app.contexts.qa.infrastructure.models import VoteModel


def net_votes_expr() -> ColumnElement[int]:
    """净票数表达式（v3 裁定 #1：up − down）：赞成 +1、反对 −1 求和，无票为 0。"""
    return func.coalesce(
        func.sum(case((VoteModel.direction == VoteDirection.UP.value, 1), else_=-1)),
        0,
    )
