"""F15 管理员用户管理与 DB 实时 RBAC 接口集成测试（真实 PG + Redis）。"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.contexts.identity.infrastructure.models import UserRoleModel
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
        "email": f"f15-adm-{uuid.uuid4().hex[:10]}@campus.edu.cn",
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
        "identifier": ident,
        "email": str(payload["email"]),
    }


async def _bootstrap_admin(client: httpx.AsyncClient) -> dict[str, str]:
    teacher = await _register_and_login(client, role="teacher", nickname="系统管理员")
    uid = uuid.UUID(teacher["id"])
    async with session_factory() as session:
        await SqlAlchemyUserRepository(session).update_role(uid, "admin")
        await session.commit()
    return teacher


async def test_admin_users_endpoints_auth_matrix_and_no_password_leak(
    client: httpx.AsyncClient,
) -> None:
    admin = await _bootstrap_admin(client)
    student = await _register_and_login(client, role="student")
    teacher = await _register_and_login(client, role="teacher")

    # 1. 注册端严禁提权
    for bad_role in ("ta", "admin"):
        reg_bad = await client.post(
            "/api/v1/auth/register",
            json={
                "role": bad_role,
                "email": f"bad-{uuid.uuid4().hex[:8]}@campus.edu.cn",
                "password": "Passw0rd8",
                "staff_id": f"T{uuid.uuid4().int % 90_000_000 + 10_000_000}",
            },
        )
        assert reg_bad.status_code == 422

    # 2. 未登录 401，非 admin（student / teacher / ta）均 403
    assert (await client.get("/api/v1/admin/users")).status_code == 401
    assert (
        await client.patch(
            f"/api/v1/admin/users/{student['id']}/role", json={"role": "ta"}
        )
    ).status_code == 401

    for actor in (student, teacher):
        assert (
            await client.get("/api/v1/admin/users", headers=_auth(actor["token"]))
        ).status_code == 403
        assert (
            await client.patch(
                f"/api/v1/admin/users/{student['id']}/role",
                json={"role": "ta"},
                headers=_auth(actor["token"]),
            )
        ).status_code == 403

    # 3. 管理员列表返回 200 且绝不泄露 password_hash
    listed = await client.get(
        "/api/v1/admin/users", params={"page": 1, "page_size": 50}, headers=_auth(admin["token"])
    )
    assert listed.status_code == 200, listed.text
    assert "password_hash" not in listed.text
    data = listed.json()
    assert set(data.keys()) == {"items", "total", "page", "page_size", "total_pages"}
    item_by_id = {item["id"]: item for item in data["items"]}
    assert student["id"] in item_by_id
    assert set(item_by_id[student["id"]].keys()) == {
        "id",
        "role",
        "email",
        "student_id",
        "staff_id",
        "display_name",
        "nickname",
        "college",
        "class_name",
        "email_verified",
        "created_at",
    }

    # 4. 禁止修改本人角色 409；不存在用户 404；非法请求体 422
    self_resp = await client.patch(
        f"/api/v1/admin/users/{admin['id']}/role",
        json={"role": "student"},
        headers=_auth(admin["token"]),
    )
    assert self_resp.status_code == 409
    assert self_resp.json() == {"detail": "不可修改本人角色"}

    missing_resp = await client.patch(
        f"/api/v1/admin/users/{uuid.uuid4()}/role",
        json={"role": "ta"},
        headers=_auth(admin["token"]),
    )
    assert missing_resp.status_code == 404
    assert missing_resp.json() == {"detail": "用户不存在"}

    for bad_body in ({"role": "superadmin"}, {"role": "ta", "extra": 1}):
        bad_resp = await client.patch(
            f"/api/v1/admin/users/{student['id']}/role",
            json=bad_body,
            headers=_auth(admin["token"]),
        )
        assert bad_resp.status_code == 422

    # 5. 提权为 ta 后：ta 自己调用管理员接口仍 403，且按 role=ta 过滤可见
    to_ta = await client.patch(
        f"/api/v1/admin/users/{student['id']}/role",
        json={"role": "ta"},
        headers=_auth(admin["token"]),
    )
    assert to_ta.status_code == 200, to_ta.text
    assert to_ta.json()["role"] == "ta"
    assert to_ta.json()["student_id"] == student["identifier"]
    assert to_ta.json()["display_name"] == f"助教#{uuid.UUID(student['id']).hex[:8]}"

    assert (
        await client.get("/api/v1/admin/users", headers=_auth(student["token"]))
    ).status_code == 403
    ta_list = await client.get(
        "/api/v1/admin/users",
        params={"role": "ta", "page_size": 100},
        headers=_auth(admin["token"]),
    )
    assert ta_list.status_code == 200
    assert any(item["id"] == student["id"] for item in ta_list.json()["items"])

    # 6. 幂等变更到同角色返回 200
    idem = await client.patch(
        f"/api/v1/admin/users/{student['id']}/role",
        json={"role": "ta"},
        headers=_auth(admin["token"]),
    )
    assert idem.status_code == 200
    assert idem.json()["role"] == "ta"


async def test_realtime_db_role_switch_login_preserve_and_f07_bounty_boundary(
    client: httpx.AsyncClient,
) -> None:
    """验证 DB 实时鉴权（旧 Access Token 立即生效/失效）、登录句柄保留与 F07 悬赏仍仅教师可发。"""
    admin = await _bootstrap_admin(client)
    teacher = await _register_and_login(client, role="teacher")
    student = await _register_and_login(client, role="student")

    q_resp = await client.post(
        "/api/v1/questions",
        json={
            "title": (
                "PostgreSQL 中 WAL 预写日志为何能同时保障持久性与原子性？"
                f"#{uuid.uuid4().hex[:6]}"
            ),
            "body": "在事务提交前先将日志记录刷盘，发生崩溃恢复时 Redo 与 Undo 如何协作？",
        },
        headers=_auth(student["token"]),
    )
    assert q_resp.status_code == 201
    qid = str(q_resp.json()["id"])

    a_resp = await client.post(
        f"/api/v1/questions/{qid}/answers",
        json={
            "body": "WAL 先于数据页刷盘（WAL 协议），崩溃时先重做已提交事务再回滚未提交事务。"
        },
        headers=_auth(student["token"]),
    )
    assert a_resp.status_code == 201
    aid = str(a_resp.json()["id"])

    # student 持有旧 Access Token：提权前认证回答被拒 403
    old_token = student["token"]
    assert (
        await client.post(f"/api/v1/answers/{aid}/verify", headers=_auth(old_token))
    ).status_code == 403

    # 管理员将其改为 ta → 不重新登录，同一旧 Token 下次请求立即生效（200）
    assert (
        await client.patch(
            f"/api/v1/admin/users/{student['id']}/role",
            json={"role": "ta"},
            headers=_auth(admin["token"]),
        )
    ).status_code == 200
    verify_ok = await client.post(
        f"/api/v1/answers/{aid}/verify", headers=_auth(old_token)
    )
    assert verify_ok.status_code == 200, verify_ok.text
    assert verify_ok.json()["is_teacher_verified"] is True

    # 变更为 ta 后仍可用原学号登录，且 /auth/me 反映新角色
    relogin = await client.post(
        "/api/v1/auth/login",
        json={"identifier": student["identifier"], "password": "Passw0rd8"},
    )
    assert relogin.status_code == 200
    me = await client.get(
        "/api/v1/auth/me", headers=_auth(relogin.json()["access_token"])
    )
    assert me.status_code == 200
    assert me.json()["role"] == "ta"

    # F07 悬赏权限保持仅 teacher 可发起（ta 与 admin 均 403，teacher 201）
    assert (
        await client.post(
            f"/api/v1/questions/{qid}/bounty",
            json={"amount": 10},
            headers=_auth(old_token),
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/questions/{qid}/bounty",
            json={"amount": 10},
            headers=_auth(admin["token"]),
        )
    ).status_code == 403
    assert (
        await client.post(
            f"/api/v1/questions/{qid}/bounty",
            json={"amount": 10},
            headers=_auth(teacher["token"]),
        )
    ).status_code == 201

    # 管理员将其降回 student → 同一旧 Token 下次请求立即失效（403）
    assert (
        await client.patch(
            f"/api/v1/admin/users/{student['id']}/role",
            json={"role": "student"},
            headers=_auth(admin["token"]),
        )
    ).status_code == 200
    assert (
        await client.delete(f"/api/v1/answers/{aid}/verify", headers=_auth(old_token))
    ).status_code == 403

    # 管理员用原工号也可登录
    admin_relogin = await client.post(
        "/api/v1/auth/login",
        json={"identifier": admin["identifier"], "password": "Passw0rd8"},
    )
    assert admin_relogin.status_code == 200


async def test_concurrent_admin_role_changes_preserve_unique_role_row(
    client: httpx.AsyncClient,
) -> None:
    admin = await _bootstrap_admin(client)
    target = await _register_and_login(client, role="student")
    target_uid = uuid.UUID(target["id"])

    roles = ["ta", "admin", "teacher", "ta", "student"]
    responses = await asyncio.gather(
        *(
            client.patch(
                f"/api/v1/admin/users/{target['id']}/role",
                json={"role": r},
                headers=_auth(admin["token"]),
            )
            for r in roles
        )
    )
    assert all(r.status_code == 200 for r in responses)

    async with session_factory() as session:
        count = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(UserRoleModel)
                    .where(UserRoleModel.user_id == target_uid)
                )
            ).scalar_one()
        )
    assert count == 1
