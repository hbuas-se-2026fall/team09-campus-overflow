"""SqlAlchemyUserRepository F15 仓储集成测试（真实 PG）。"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from app.contexts.identity.application.commands import RegisterCommand
from app.contexts.identity.application.register_use_case import RegisterUseCase
from app.contexts.identity.domain.errors import UserNotFoundError
from app.contexts.identity.domain.user import Role
from app.contexts.identity.infrastructure.models import UserRoleModel
from app.contexts.identity.infrastructure.password_hasher import BcryptPasswordHasher
from app.contexts.identity.infrastructure.repository import SqlAlchemyUserRepository
from app.shared.engine import session_factory

pytestmark = pytest.mark.integration


async def _register_student() -> tuple[uuid.UUID, str]:
    email = f"f15-repo-{uuid.uuid4().hex[:10]}@stu.edu.cn"
    student_id = str(uuid.uuid4().int)[:10]
    async with session_factory() as session:
        user = await RegisterUseCase(
            SqlAlchemyUserRepository(session), BcryptPasswordHasher()
        ).execute(
            RegisterCommand(
                role="student",
                email=email,
                password="Passw0rd8",
                student_id=student_id,
            )
        )
        await session.commit()
        return user.id, student_id


async def _register_teacher() -> tuple[uuid.UUID, str]:
    email = f"f15-repo-t-{uuid.uuid4().hex[:10]}@edu.cn"
    staff_id = f"T{uuid.uuid4().int % 90_000_000 + 10_000_000}"
    async with session_factory() as session:
        user = await RegisterUseCase(
            SqlAlchemyUserRepository(session), BcryptPasswordHasher()
        ).execute(
            RegisterCommand(
                role="teacher",
                email=email,
                password="Passw0rd8",
                staff_id=staff_id,
            )
        )
        await session.commit()
        return user.id, staff_id


async def _role_row_count(user_id: uuid.UUID) -> int:
    async with session_factory() as session:
        return int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(UserRoleModel)
                    .where(UserRoleModel.user_id == user_id)
                )
            ).scalar_one()
        )


async def test_update_role_preserves_handles_and_single_role_invariant() -> None:
    stu_uid, student_id = await _register_student()
    tch_uid, staff_id = await _register_teacher()

    async with session_factory() as session:
        repo = SqlAlchemyUserRepository(session)
        promoted_ta = await repo.update_role(stu_uid, "ta")
        promoted_admin = await repo.update_role(tch_uid, "admin")
        await session.commit()

    assert promoted_ta.role == "ta"
    assert promoted_ta.student_id is not None and promoted_ta.student_id.value == student_id
    assert promoted_ta.staff_id is None
    assert await _role_row_count(stu_uid) == 1

    assert promoted_admin.role == "admin"
    assert promoted_admin.staff_id is not None and promoted_admin.staff_id.value == staff_id
    assert promoted_admin.student_id is None
    assert await _role_row_count(tch_uid) == 1

    # 原学号/工号仍可正常查到用户且带新角色
    async with session_factory() as session:
        repo = SqlAlchemyUserRepository(session)
        by_stu = await repo.get_by_student_id(student_id)
        by_staff = await repo.get_by_staff_id(staff_id)
        assert by_stu is not None and by_stu.role == "ta"
        assert by_staff is not None and by_staff.role == "admin"

    # 不存在用户抛 UserNotFoundError
    async with session_factory() as session:
        with pytest.raises(UserNotFoundError):
            await SqlAlchemyUserRepository(session).update_role(uuid.uuid4(), "ta")


async def test_list_paginated_orders_desc_and_filters_by_role() -> None:
    u1, _ = await _register_student()
    u2, _ = await _register_student()
    async with session_factory() as session:
        repo = SqlAlchemyUserRepository(session)
        await repo.update_role(u2, "ta")
        await session.commit()

    async with session_factory() as session:
        repo = SqlAlchemyUserRepository(session)
        page1, total_all = await repo.list_paginated(page=1, page_size=20, role=None)
        ta_items, total_ta = await repo.list_paginated(page=1, page_size=50, role="ta")
        beyond_items, total_ta_beyond = await repo.list_paginated(
            page=99999, page_size=20, role="ta"
        )

    assert total_all >= 2
    ids_all = [u.id for u in page1]
    assert u2 in ids_all and u1 in ids_all
    assert ids_all.index(u2) < ids_all.index(u1)

    ta_ids = [u.id for u in ta_items]
    assert u2 in ta_ids
    assert u1 not in ta_ids
    assert total_ta == total_ta_beyond >= 1
    assert beyond_items == []


async def test_concurrent_update_role_maintains_single_user_role_row() -> None:
    uid, student_id = await _register_student()
    target_roles: list[Role] = ["ta", "admin", "teacher", "student", "ta"]

    async def _worker(role: Role) -> Role:
        async with session_factory() as session:
            updated = await SqlAlchemyUserRepository(session).update_role(uid, role)
            await session.commit()
            return updated.role

    results = await asyncio.gather(*(_worker(r) for r in target_roles))
    assert set(results) <= set(target_roles)
    assert await _role_row_count(uid) == 1

    async with session_factory() as session:
        fetched = await SqlAlchemyUserRepository(session).get_by_student_id(student_id)
        assert fetched is not None
        assert fetched.role in target_roles
