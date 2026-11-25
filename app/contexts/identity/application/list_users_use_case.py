"""管理员分页查询用户列表用例（F15）。"""

from __future__ import annotations

import math
from dataclasses import dataclass

from app.contexts.identity.application.queries import ListUsersQuery
from app.contexts.identity.domain.repository import UserRepository
from app.contexts.identity.domain.user import User


@dataclass(frozen=True, slots=True)
class UserPage:
    """用户列表分页结果（total_pages = ceil(total/page_size)，空库为 0）。"""

    items: list[User]
    total: int
    page: int
    page_size: int
    total_pages: int


class ListUsersUseCase:
    """分页列出用户（支持按角色过滤），元数据与列表同口径。"""

    def __init__(self, repository: UserRepository) -> None:
        self._repository = repository

    async def execute(self, query: ListUsersQuery) -> UserPage:
        items, total = await self._repository.list_paginated(
            page=query.page,
            page_size=query.page_size,
            role=query.role,
        )
        return UserPage(
            items=items,
            total=total,
            page=query.page,
            page_size=query.page_size,
            total_pages=math.ceil(total / query.page_size) if total else 0,
        )
