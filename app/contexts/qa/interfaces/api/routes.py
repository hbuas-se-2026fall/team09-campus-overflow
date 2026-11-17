"""qa 路由汇总：按资源拆分后在此保持对外导出稳定（main.py 无需改动）。"""

from __future__ import annotations

from app.contexts.qa.interfaces.api.answers import answers_router
from app.contexts.qa.interfaces.api.badges import router as badges_router
from app.contexts.qa.interfaces.api.bounty import bounty_router
from app.contexts.qa.interfaces.api.points import points_router
from app.contexts.qa.interfaces.api.questions import router
from app.contexts.qa.interfaces.api.tags import tags_router

__all__ = [
    "answers_router",
    "badges_router",
    "bounty_router",
    "points_router",
    "router",
    "tags_router",
]
