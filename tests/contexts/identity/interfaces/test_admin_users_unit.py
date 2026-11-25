"""F15 管理员用户接口单元测试（dependency_overrides，不连库，进 CI）。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from app.contexts.identity.domain.errors import UserNotFoundError
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
from app.contexts.identity.interfaces.api.deps import (
    get_current_user,
    get_user_repository,
)
from app.main import create_app
from app.shared.sentinel import UNSET, UnsetType


def _user(role: Role, *, student_id: str | None = None, staff_id: str | None = None) -> User:
    return User(
        id=uuid4(),
        role=role,
        email=Email(f"{uuid4().hex[:8]}@campus.edu.cn"),
        password_hash=PasswordHash("$2b$12$abcdefghijklmnopqrstuv"),
        student_id=StudentId(student_id) if student_id else None,
        staff_id=StaffId(staff_id) if staff_id else None,
        created_at=datetime(2026, 11, 25, 9, 0, tzinfo=UTC),
    )


class _FakeAdminRepo:
    def __init__(self, users: list[User]) -> None:
        self._users = {u.id: u for u in users}

    async def get_by_email(self, email: str) -> User | None:
        return None

    async def get_by_student_id(self, student_id: str) -> User | None:
        return None

    async def get_by_staff_id(self, staff_id: str) -> User | None:
        return None

    async def get_by_id(self, user_id: UUID, *, for_update: bool = False) -> User | None:
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
        items = [u for u in self._users.values() if role is None or u.role == role]
        items.sort(key=lambda u: (u.created_at, u.id), reverse=True)
        start = (page - 1) * page_size
        return items[start : start + page_size], len(items)

    async def update_role(self, user_id: UUID, new_role: Role) -> User:
        user = self._users.get(user_id)
        if user is None:
            raise UserNotFoundError("用户不存在")
        user.change_role(new_role)
        return user


@pytest.mark.parametrize("role", ["student", "teacher", "ta"])
async def test_admin_endpoints_reject_non_admin_with_403(role: Role) -> None:
    actor = _user(role, student_id="2025010101" if role in ("student", "ta") else None)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: actor
    app.dependency_overrides[get_user_repository] = lambda: _FakeAdminRepo([actor])

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        r1 = await client.get("/api/v1/admin/users")
        assert r1.status_code == 403
        r2 = await client.patch(
            f"/api/v1/admin/users/{uuid4()}/role", json={"role": "ta"}
        )
        assert r2.status_code == 403


async def test_admin_list_and_role_update_routes_unit() -> None:
    admin = _user("admin", staff_id="T90001")
    student = _user("student", student_id="2025010101")
    app = create_app()
    repo = _FakeAdminRepo([admin, student])
    app.dependency_overrides[get_current_user] = lambda: admin
    app.dependency_overrides[get_user_repository] = lambda: repo

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        listed = await client.get("/api/v1/admin/users", params={"role": "student"})
        assert listed.status_code == 200
        body = listed.json()
        assert body["total"] == 1
        assert body["items"][0]["id"] == str(student.id)
        assert "password_hash" not in body["items"][0]

        changed = await client.patch(
            f"/api/v1/admin/users/{student.id}/role", json={"role": "ta"}
        )
        assert changed.status_code == 200
        assert changed.json()["role"] == "ta"
        assert changed.json()["display_name"] == f"助教#{student.id.hex[:8]}"

        self_err = await client.patch(
            f"/api/v1/admin/users/{admin.id}/role", json={"role": "teacher"}
        )
        assert self_err.status_code == 409
        assert self_err.json() == {"detail": "不可修改本人角色"}

        missing = await client.patch(
            f"/api/v1/admin/users/{uuid4()}/role", json={"role": "ta"}
        )
        assert missing.status_code == 404
        assert missing.json() == {"detail": "用户不存在"}
