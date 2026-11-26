"""RegisterUseCase 单元测试：fake 仓储 + fake 哈希器，不连库。"""

from uuid import UUID

import pytest

from app.contexts.identity.application.commands import RegisterCommand
from app.contexts.identity.application.register_use_case import RegisterUseCase
from app.contexts.identity.domain.errors import (
    EmailAlreadyExistsError,
    IdentityAlreadyExistsError,
    IdentityRequiredError,
    UnknownRoleError,
    UserNotFoundError,
    WeakPasswordError,
)
from app.contexts.identity.domain.user import Role, User


class FakeRepository:
    def __init__(self) -> None:
        self.saved: list[User] = []

    async def get_by_email(self, email: str) -> User | None:
        return next((u for u in self.saved if u.email.value == email), None)

    async def get_by_student_id(self, student_id: str) -> User | None:
        return next(
            (
                u
                for u in self.saved
                if u.student_id is not None and u.student_id.value == student_id
            ),
            None,
        )

    async def get_by_staff_id(self, staff_id: str) -> User | None:
        return next(
            (u for u in self.saved if u.staff_id is not None and u.staff_id.value == staff_id),
            None,
        )

    async def add(self, user: User) -> None:
        self.saved.append(user)

    async def get_by_id(self, user_id: UUID, *, for_update: bool = False) -> User | None:
        return next((u for u in self.saved if u.id == user_id), None)

    async def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        role: Role | None = None,
    ) -> tuple[list[User], int]:
        filtered = [u for u in self.saved if role is None or u.role == role]
        filtered.sort(key=lambda u: (u.created_at, u.id), reverse=True)
        start = (page - 1) * page_size
        return filtered[start : start + page_size], len(filtered)

    async def update_role(self, user_id: UUID, new_role: Role) -> User:
        user = await self.get_by_id(user_id)
        if user is None:
            raise UserNotFoundError("用户不存在")
        user.change_role(new_role)
        return user


class FakeHasher:
    async def hash(self, plain: str) -> str:
        return f"$2b$12$fakehashfor{plain}"


def _use_case() -> tuple[RegisterUseCase, FakeRepository]:
    repo = FakeRepository()
    return RegisterUseCase(repo, FakeHasher()), repo


async def test_register_student_success() -> None:
    use_case, repo = _use_case()
    user = await use_case.execute(
        RegisterCommand(
            role="student",
            email="zhang@stu.edu.cn",
            password="Passw0rd8",
            student_id="2025010101",
        )
    )
    assert len(repo.saved) == 1
    assert user.role == "student"
    assert user.password_hash.value == "$2b$12$fakehashforPassw0rd8"  # 已哈希，非明文
    assert user.events[0].role == "student"


async def test_register_teacher_success() -> None:
    use_case, repo = _use_case()
    user = await use_case.execute(
        RegisterCommand(role="teacher", email="li@edu.cn", password="Passw0rd8", staff_id="T10086")
    )
    assert len(repo.saved) == 1
    assert user.role == "teacher"


async def test_duplicate_email_rejected() -> None:
    use_case, _ = _use_case()
    cmd = RegisterCommand(
        role="student", email="zhang@stu.edu.cn", password="Passw0rd8", student_id="2025010101"
    )
    await use_case.execute(cmd)
    with pytest.raises(EmailAlreadyExistsError):
        await use_case.execute(
            RegisterCommand(
                role="student",
                email="zhang@stu.edu.cn",
                password="Passw0rd8",
                student_id="2025010102",
            )
        )


async def test_duplicate_student_id_rejected() -> None:
    use_case, _ = _use_case()
    await use_case.execute(
        RegisterCommand(
            role="student", email="a@stu.edu.cn", password="Passw0rd8", student_id="2025010101"
        )
    )
    with pytest.raises(IdentityAlreadyExistsError):
        await use_case.execute(
            RegisterCommand(
                role="student",
                email="b@stu.edu.cn",
                password="Passw0rd8",
                student_id="2025010101",
            )
        )


async def test_weak_password_rejected() -> None:
    use_case, repo = _use_case()
    with pytest.raises(WeakPasswordError):
        await use_case.execute(
            RegisterCommand(
                role="student",
                email="a@stu.edu.cn",
                password="abc123",
                student_id="2025010101",
            )
        )
    assert repo.saved == []  # 不产生副作用


async def test_student_without_student_id_rejected() -> None:
    use_case, _ = _use_case()
    with pytest.raises(IdentityRequiredError):
        await use_case.execute(
            RegisterCommand(role="student", email="a@stu.edu.cn", password="Passw0rd8")
        )


async def test_invalid_student_id_format_rejected() -> None:
    use_case, repo = _use_case()
    with pytest.raises(ValueError, match="学号"):
        await use_case.execute(
            RegisterCommand(
                role="student", email="a@stu.edu.cn", password="Passw0rd8", student_id="abc!!!"
            )
        )
    assert repo.saved == []


@pytest.mark.parametrize("privileged_role", ["ta", "admin"])
async def test_register_rejects_ta_and_admin_roles(privileged_role: str) -> None:
    use_case, repo = _use_case()
    with pytest.raises(UnknownRoleError):
        await use_case.execute(
            RegisterCommand(
                role=privileged_role,
                email="priv@campus.edu.cn",
                password="Passw0rd8",
                staff_id="T10086",
            )
        )
    assert repo.saved == []
