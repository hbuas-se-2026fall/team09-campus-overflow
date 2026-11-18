from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.contexts.identity.domain.user import User
from app.contexts.identity.domain.value_objects import ClassName, College, Nickname
from app.shared.sentinel import UNSET, UnsetType


class UserRepository(Protocol):
    """用户聚合持久化端口：domain 定义接口，infrastructure 实现。"""

    async def get_by_email(self, email: str) -> User | None:
        """按邮箱查询用户。"""
        ...

    async def get_by_student_id(self, student_id: str) -> User | None:
        """按学号查询用户。"""
        ...

    async def get_by_staff_id(self, staff_id: str) -> User | None:
        """按工号查询用户。"""
        ...

    async def get_by_id(self, user_id: UUID, *, for_update: bool = False) -> User | None:
        """按用户 ID 查询（for_update=True 时加主表行锁并刷新实体）。"""
        ...

    async def add(self, user: User) -> None:
        """新增用户（聚合整体落库）。"""
        ...

    async def update_profile(
        self,
        user_id: UUID,
        *,
        nickname: Nickname | None | UnsetType = UNSET,
        college: College | None | UnsetType = UNSET,
        class_name: ClassName | None | UnsetType = UNSET,
    ) -> User | None:
        """F10：定向更新校园资料字段（只改显式传入的列，不覆盖 email_verified）。"""
        ...

    async def mark_email_verified(self, user_id: UUID) -> None:
        """F10：定向将 email_verified 置为 True（不覆盖资料列）。"""
        ...
