"""F16 课程上下文与选课 API 集成及并发测试（真实 PG + Redis）。"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, func, select

from app.contexts.course.infrastructure.models import CourseModel, EnrollmentModel
from app.contexts.identity.infrastructure.models import UserModel
from app.contexts.identity.infrastructure.repository import SqlAlchemyUserRepository
from app.main import create_app
from app.shared.engine import session_factory

pytestmark = pytest.mark.integration

BASE_URL = "http://test"


@pytest.fixture
async def client(redis_cleanup: None) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as c:
        yield c


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register_and_login(
    client: httpx.AsyncClient,
    *,
    role: str = "student",
    nickname: str | None = None,
) -> dict[str, str]:
    ident = (
        str(uuid.uuid4().int)[:10]
        if role == "student"
        else f"T{uuid.uuid4().int % 90_000_000 + 10_000_000}"
    )
    payload: dict[str, Any] = {
        "role": role,
        "email": f"f16-{uuid.uuid4().hex[:10]}@campus.edu.cn",
        "password": "Passw0rd8",
    }
    if role == "student":
        payload["student_id"] = ident
    else:
        payload["staff_id"] = ident
    reg = await client.post("/api/v1/auth/register", json=payload)
    assert reg.status_code == 201, reg.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"identifier": ident, "password": "Passw0rd8"},
    )
    assert login.status_code == 200, login.text
    token = str(login.json()["access_token"])
    if nickname is not None:
        patch = await client.patch(
            "/api/v1/auth/me/profile",
            json={"nickname": nickname},
            headers=_auth(token),
        )
        assert patch.status_code == 200, patch.text
    return {
        "id": str(reg.json()["id"]),
        "token": token,
    }


async def _promote_role(user_id: str, new_role: str) -> None:
    uid = uuid.UUID(user_id)
    async with session_factory() as session:
        await SqlAlchemyUserRepository(session).update_role(uid, new_role)  # type: ignore[arg-type]
        await session.commit()


async def _cleanup(course_ids: list[uuid.UUID], user_ids: list[uuid.UUID]) -> None:
    async with session_factory() as session:
        if course_ids:
            await session.execute(
                delete(CourseModel).where(CourseModel.id.in_(course_ids))
            )
        if user_ids:
            await session.execute(
                delete(UserModel).where(UserModel.id.in_(user_ids))
            )
        await session.commit()


async def test_course_api_full_rbac_matrix_pagination_and_minimal_disclosure(
    client: httpx.AsyncClient,
) -> None:
    suffix = uuid.uuid4().hex[:6].upper()
    sem_fall = f"2026-Fall-{suffix}"
    sem_spring = f"2026-Spring-{suffix}"

    teacher = await _register_and_login(client, role="teacher", nickname="软件工程教师")
    admin_base = await _register_and_login(client, role="teacher", nickname="教务管理员")
    await _promote_role(admin_base["id"], "admin")
    ta_base = await _register_and_login(client, role="student", nickname="课程助教")
    await _promote_role(ta_base["id"], "ta")
    student1 = await _register_and_login(client, role="student", nickname="选课学生甲")
    student2 = await _register_and_login(client, role="student", nickname="选课学生乙")

    user_ids = [
        uuid.UUID(u["id"])
        for u in (teacher, admin_base, ta_base, student1, student2)
    ]
    course_ids: list[uuid.UUID] = []

    try:
        # 1. 未认证 401
        assert (
            await client.post(
                "/api/v1/courses",
                json={
                    "code": f"CS-SE-{suffix}",
                    "name": "软件工程",
                    "semester": sem_fall,
                },
            )
        ).status_code == 401
        assert (
            await client.post(f"/api/v1/courses/{uuid.uuid4()}/enroll")
        ).status_code == 401
        assert (
            await client.get(f"/api/v1/courses/{uuid.uuid4()}/students")
        ).status_code == 401

        # 2. 创建课程权限矩阵：student/ta 403，teacher/admin 201
        for actor in (student1, ta_base):
            resp = await client.post(
                "/api/v1/courses",
                json={
                    "code": f"CS-DENY-{suffix}",
                    "name": "软件工程",
                    "semester": sem_fall,
                },
                headers=_auth(actor["token"]),
            )
            assert resp.status_code == 403

        create_se = await client.post(
            "/api/v1/courses",
            json={
                "code": f" cs-se-{suffix} ",
                "name": "软件工程",
                "semester": sem_fall,
            },
            headers=_auth(teacher["token"]),
        )
        assert create_se.status_code == 201, create_se.text
        se_data = create_se.json()
        course_ids.append(uuid.UUID(se_data["id"]))
        assert se_data["code"] == f"CS-SE-{suffix}"
        assert se_data["teacher_name"] == "软件工程教师"

        # 大小写等价重复课程码 -> 409
        dup_se = await client.post(
            "/api/v1/courses",
            json={
                "code": f"CS-SE-{suffix}",
                "name": "软件工程重开",
                "semester": sem_fall,
            },
            headers=_auth(admin_base["token"]),
        )
        assert dup_se.status_code == 409

        # admin 创建第二门课程（操作系统）
        create_os = await client.post(
            "/api/v1/courses",
            json={
                "code": f"CS-OS-{suffix}",
                "name": "操作系统",
                "semester": sem_spring,
            },
            headers=_auth(admin_base["token"]),
        )
        assert create_os.status_code == 201, create_os.text
        course_ids.append(uuid.UUID(create_os.json()["id"]))

        # 3. 公开列表查询 + semester 筛选 + total 与库 COUNT 对账 + teacher_name 回填
        async with session_factory() as session:
            total_in_db = int(
                (
                    await session.execute(select(func.count()).select_from(CourseModel))
                ).scalar_one()
            )
        all_resp = await client.get("/api/v1/courses", params={"page": 1, "page_size": 20})
        assert all_resp.status_code == 200
        assert all_resp.json()["total"] == total_in_db

        fall_resp = await client.get(
            "/api/v1/courses", params={"semester": sem_fall, "page": 1, "page_size": 10}
        )
        assert fall_resp.status_code == 200
        fall_json = fall_resp.json()
        assert fall_json["total"] == 1
        assert fall_json["total_pages"] == 1
        assert fall_json["items"][0]["code"] == f"CS-SE-{suffix}"
        assert fall_json["items"][0]["teacher_name"] == "软件工程教师"

        invalid_sem = await client.get("/api/v1/courses", params={"semester": "X"})
        assert invalid_sem.status_code == 422

        # 4. 选课权限矩阵与幂等冲突：teacher/ta/admin 403，student 201，重复 409，缺课 404
        se_id = se_data["id"]
        for actor in (teacher, ta_base, admin_base):
            denied = await client.post(
                f"/api/v1/courses/{se_id}/enroll", headers=_auth(actor["token"])
            )
            assert denied.status_code == 403

        e1 = await client.post(
            f"/api/v1/courses/{se_id}/enroll", headers=_auth(student1["token"])
        )
        assert e1.status_code == 201, e1.text
        assert e1.json()["student_name"] == "选课学生甲"

        e1_dup = await client.post(
            f"/api/v1/courses/{se_id}/enroll", headers=_auth(student1["token"])
        )
        assert e1_dup.status_code == 409

        e2 = await client.post(
            f"/api/v1/courses/{se_id}/enroll", headers=_auth(student2["token"])
        )
        assert e2.status_code == 201, e2.text

        assert (
            await client.post(
                f"/api/v1/courses/{uuid.uuid4()}/enroll",
                headers=_auth(student1["token"]),
            )
        ).status_code == 404

        # 5. 选课学生列表权限矩阵 + 分页 + 最小披露 + F11 回填
        assert (
            await client.get(
                f"/api/v1/courses/{se_id}/students", headers=_auth(student1["token"])
            )
        ).status_code == 403

        for staff in (teacher, ta_base, admin_base):
            page1 = await client.get(
                f"/api/v1/courses/{se_id}/students",
                params={"page": 1, "page_size": 1},
                headers=_auth(staff["token"]),
            )
            assert page1.status_code == 200, page1.text
            p1_json = page1.json()
            assert p1_json["total"] == 2
            assert p1_json["total_pages"] == 2
            item = p1_json["items"][0]
            assert set(item.keys()) == {"student_id", "student_name", "enrolled_at"}
            assert item["student_name"] == "选课学生甲"

        assert (
            await client.get(
                f"/api/v1/courses/{uuid.uuid4()}/students",
                headers=_auth(teacher["token"]),
            )
        ).status_code == 404
    finally:
        await _cleanup(course_ids, user_ids)


async def test_course_creation_and_enrollment_concurrency(
    client: httpx.AsyncClient,
) -> None:
    suffix = uuid.uuid4().hex[:6].upper()
    code_upper = f"CS-DB-{suffix}"
    code_lower = f"cs-db-{suffix}"
    sem = f"2026-Fall-{suffix}"

    teacher = await _register_and_login(client, role="teacher", nickname="数据库教师")
    student = await _register_and_login(client, role="student", nickname="并发选课学生")

    user_ids = [uuid.UUID(teacher["id"]), uuid.UUID(student["id"])]
    course_ids: list[uuid.UUID] = []

    try:
        # 1. 6 路并发创建同一规范化课程编号（大小写混传）：仅 1 个 201，其余 5 个 409
        create_tasks = [
            client.post(
                "/api/v1/courses",
                json={
                    "code": code_upper if idx % 2 == 0 else code_lower,
                    "name": "数据库系统原理",
                    "semester": sem,
                },
                headers=_auth(teacher["token"]),
            )
            for idx in range(6)
        ]
        create_responses = await asyncio.gather(*create_tasks)
        statuses = [resp.status_code for resp in create_responses]
        assert statuses.count(201) == 1, statuses
        assert statuses.count(409) == 5, statuses

        winner = next(resp for resp in create_responses if resp.status_code == 201)
        course_id = uuid.UUID(winner.json()["id"])
        course_ids.append(course_id)

        async with session_factory() as session:
            db_courses = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(CourseModel)
                        .where(CourseModel.code == code_upper)
                    )
                ).scalar_one()
            )
            assert db_courses == 1

        # 2. 6 路并发同学生同课程选课：仅 1 个 201，其余 5 个 409
        enroll_tasks = [
            client.post(
                f"/api/v1/courses/{course_id}/enroll",
                headers=_auth(student["token"]),
            )
            for _ in range(6)
        ]
        enroll_responses = await asyncio.gather(*enroll_tasks)
        enroll_statuses = [resp.status_code for resp in enroll_responses]
        assert enroll_statuses.count(201) == 1, enroll_statuses
        assert enroll_statuses.count(409) == 5, enroll_statuses

        async with session_factory() as session:
            db_enrolls = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(EnrollmentModel)
                        .where(
                            EnrollmentModel.course_id == course_id,
                            EnrollmentModel.student_id == uuid.UUID(student["id"]),
                        )
                    )
                ).scalar_one()
            )
            assert db_enrolls == 1
    finally:
        await _cleanup(course_ids, user_ids)
