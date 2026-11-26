"""用户管理只读查询 DTO（F15）。"""

from __future__ import annotations

from dataclasses import dataclass

from app.contexts.identity.domain.user import Role


@dataclass(frozen=True, slots=True)
class ListUsersQuery:
    """管理员分页查询用户列表参数（边界由路由 Query 校验后传入）。"""

    page: int = 1
    page_size: int = 20
    role: Role | None = None
