"""管理员变更用户角色用例（F15）。"""

from __future__ import annotations

from app.contexts.identity.application.commands import UpdateUserRoleCommand
from app.contexts.identity.domain.errors import SelfRoleChangeError, UserNotFoundError
from app.contexts.identity.domain.repository import UserRepository
from app.contexts.identity.domain.user import User


class UpdateUserRoleUseCase:
    """管理员变更目标用户角色：
    1. actor_id == target_user_id → SelfRoleChangeError（409）
    2. get_by_id(..., for_update=True) 不存在 → UserNotFoundError（404）
    3. 领域校验 change_role 并原子替换唯一角色行（保留学工号，幂等返回刷新后的 User）
    """

    def __init__(self, repository: UserRepository) -> None:
        self._repository = repository

    async def execute(self, command: UpdateUserRoleCommand) -> User:
        if command.actor_id == command.target_user_id:
            raise SelfRoleChangeError("不可修改本人角色")
        user = await self._repository.get_by_id(command.target_user_id, for_update=True)
        if user is None:
            raise UserNotFoundError("用户不存在")
        user.change_role(command.new_role)
        return await self._repository.update_role(user.id, user.role)
