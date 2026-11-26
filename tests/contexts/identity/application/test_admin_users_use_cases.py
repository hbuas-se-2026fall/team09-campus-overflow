"""F15 管理员用户列表与角色变更用例 + 注册禁提权单元测试（不连库，进 CI）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest

from app.contexts.identity.application.commands import UpdateUserRoleCommand
from app.contexts.identity.application.list_users_use_case import ListUsersUseCase
from app.contexts.identity.application.queries import ListUsersQuery
from app.contexts.identity.application.update_user_role_use_case import (
    UpdateUserRoleUseCase,
)
from app.contexts.identity.domain.errors import SelfRoleChangeError, UserNotFoundError
from app.contexts.identity.domain.user import Role, User
from app.contexts.identity.domain.value_objects import (
    ClassName,
    College,
    Email,
    Nickname,
    PasswordHash,
    StaffId,
    StudentId,
)
from app.main import create_app
from app.shared.sentinel import UNSET, UnsetType


def _make_user(
    *,
    role: Role = "student",
    email: str = "stu@campus.edu.cn",
    student_id: str | None = "2025010101",
    staff_id: str | None = None,
    created_at: datetime | None = None,
) -> User:
    return User(
        id=uuid4(),
        role=role,
        email=Email(email),
        password_hash=PasswordHash("$2b$12$abcdefghijklmnopqrstuv"),
        student_id=StudentId(student_id) if student_id is not None else None,
        staff_id=StaffId(staff_id) if staff_id is not None else None,
        created_at=created_at or datetime.now(UTC),
    )


class FakeUserRepository:
    def __init__(self, users: list[User]) -> None:
        self._users = {u.id: u for u in users}
        self.for_update_calls: list[tuple[UUID, bool]] = []
        self.role_updates: list[tuple[UUID, Role]] = []

    async def get_by_email(self, email: str) -> User | None:
        return next((u for u in self._users.values() if u.email.value == email), None)

    async def get_by_student_id(self, student_id: str) -> User | None:
        return next(
            (
                u
                for u in self._users.values()
                if u.student_id is not None and u.student_id.value == student_id
            ),
            None,
        )

    async def get_by_staff_id(self, staff_id: str) -> User | None:
        return next(
            (
                u
                for u in self._users.values()
                if u.staff_id is not None and u.staff_id.value == staff_id
            ),
            None,
        )

    async def get_by_id(self, user_id: UUID, *, for_update: bool = False) -> User | None:
        self.for_update_calls.append((user_id, for_update))
        return self._users.get(user_id)

    async def add(self, user: User) -> None:
        self._users[user.id] = user

    async def update_profile(
        self,
        user_id: UUID,
        *,
        nickname: Nickname | None | UnsetType = UNSET,
        college: College | None | UnsetType = UNSET,
        class_name: ClassName | None | UnsetType = UNSET,
    ) -> User | None:
        return self._users.get(user_id)

    async def mark_email_verified(self, user_id: UUID) -> None:
        return None

    async def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        role: Role | None = None,
    ) -> tuple[list[User], int]:
        filtered = [u for u in self._users.values() if role is None or u.role == role]
        filtered.sort(key=lambda u: (u.created_at, u.id), reverse=True)
        start = (page - 1) * page_size
        return filtered[start : start + page_size], len(filtered)

    async def update_role(self, user_id: UUID, new_role: Role) -> User:
        user = self._users.get(user_id)
        if user is None:
            raise UserNotFoundError("用户不存在")
        user.change_role(new_role)
        self.role_updates.append((user_id, new_role))
        return user


async def test_list_users_paginates_orders_and_filters_by_role() -> None:
    base = datetime(2026, 11, 25, 8, 0, tzinfo=UTC)
    u1 = _make_user(
        role="student",
        email="s1@campus.edu.cn",
        student_id="2025010101",
        created_at=base,
    )
    u2 = _make_user(
        role="ta",
        email="ta1@campus.edu.cn",
        student_id="2025010102",
        created_at=base + timedelta(seconds=10),
    )
    u3 = _make_user(
        role="admin",
        email="adm@campus.edu.cn",
        student_id=None,
        staff_id="T10001",
        created_at=base + timedelta(seconds=20),
    )
    use_case = ListUsersUseCase(FakeUserRepository([u1, u2, u3]))

    page1 = await use_case.execute(ListUsersQuery(page=1, page_size=2))
    assert [u.id for u in page1.items] == [u3.id, u2.id]
    assert page1.total == 3
    assert page1.total_pages == 2

    only_ta = await use_case.execute(ListUsersQuery(page=1, page_size=20, role="ta"))
    assert [u.id for u in only_ta.items] == [u2.id]
    assert only_ta.total == 1
    assert only_ta.total_pages == 1

    empty = await use_case.execute(ListUsersQuery(page=1, page_size=20, role="teacher"))
    assert empty.items == []
    assert empty.total == 0
    assert empty.total_pages == 0


async def test_update_user_role_transitions_and_preserves_handles() -> None:
    admin = _make_user(
        role="admin", email="admin@campus.edu.cn", student_id=None, staff_id="T90001"
    )
    student = _make_user(
        role="student", email="stu@campus.edu.cn", student_id="2025010109"
    )
    repo = FakeUserRepository([admin, student])
    use_case = UpdateUserRoleUseCase(repo)

    promoted = await use_case.execute(
        UpdateUserRoleCommand(
            actor_id=admin.id, target_user_id=student.id, new_role="ta"
        )
    )
    assert promoted.role == "ta"
    assert promoted.student_id is not None and promoted.student_id.value == "2025010109"
    assert repo.for_update_calls == [(student.id, True)]

    # 幂等变更到同角色仍返回更新后 User
    same = await use_case.execute(
        UpdateUserRoleCommand(
            actor_id=admin.id, target_user_id=student.id, new_role="ta"
        )
    )
    assert same.role == "ta"


async def test_update_user_role_rejects_self_change_and_missing_user() -> None:
    admin = _make_user(
        role="admin", email="admin@campus.edu.cn", student_id=None, staff_id="T90002"
    )
    repo = FakeUserRepository([admin])
    use_case = UpdateUserRoleUseCase(repo)

    with pytest.raises(SelfRoleChangeError, match="不可修改本人角色"):
        await use_case.execute(
            UpdateUserRoleCommand(
                actor_id=admin.id, target_user_id=admin.id, new_role="student"
            )
        )
    assert repo.for_update_calls == []

    missing_id = uuid4()
    with pytest.raises(UserNotFoundError, match="用户不存在"):
        await use_case.execute(
            UpdateUserRoleCommand(
                actor_id=admin.id, target_user_id=missing_id, new_role="ta"
            )
        )
    assert repo.for_update_calls == [(missing_id, True)]


@pytest.mark.parametrize("privileged_role", ["ta", "admin"])
async def test_register_endpoint_rejects_privileged_role_422(privileged_role: str) -> None:
    """RegisterRequest 在边界层保持拒绝 ta/admin（422），不连库。"""
    app = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "role": privileged_role,
                "email": "priv@campus.edu.cn",
                "password": "Passw0rd8",
                "staff_id": "T10086",
            },
        )
    assert resp.status_code == 422
