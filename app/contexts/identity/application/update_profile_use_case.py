"""更新当前用户校园资料用例（F10）。"""

from __future__ import annotations

from app.contexts.identity.application.commands import UpdateProfileCommand
from app.contexts.identity.domain.errors import InvalidCredentialsError
from app.contexts.identity.domain.repository import UserRepository
from app.contexts.identity.domain.user import User
from app.contexts.identity.domain.value_objects import ClassName, College, Nickname
from app.shared.errors import DomainValidationError
from app.shared.sentinel import UNSET, UnsetType


class UpdateProfileUseCase:
    """局部更新昵称 / 学院 / 班级：UNSET 保持原值，None 清空，字符串经 VO 校验。"""

    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def execute(self, command: UpdateProfileCommand) -> User:
        if (
            command.nickname is UNSET
            and command.college is UNSET
            and command.class_name is UNSET
        ):
            raise DomainValidationError("至少提供一项资料字段")

        nickname_vo: Nickname | None | UnsetType = (
            UNSET
            if isinstance(command.nickname, UnsetType)
            else (None if command.nickname is None else Nickname(command.nickname))
        )
        college_vo: College | None | UnsetType = (
            UNSET
            if isinstance(command.college, UnsetType)
            else (None if command.college is None else College(command.college))
        )
        class_name_vo: ClassName | None | UnsetType = (
            UNSET
            if isinstance(command.class_name, UnsetType)
            else (None if command.class_name is None else ClassName(command.class_name))
        )

        updated = await self._users.update_profile(
            command.user_id,
            nickname=nickname_vo,
            college=college_vo,
            class_name=class_name_vo,
        )
        if updated is None:
            raise InvalidCredentialsError("用户不存在")
        return updated
