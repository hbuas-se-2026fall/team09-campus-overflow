"""个人积分余额与流水接口集成测试（F07 闭环）：401/教师惰性开户/冻结/获奖/学生空账户。"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest

from app.contexts.reputation.infrastructure.celery_app import celery_app
from app.main import create_app

pytestmark = pytest.mark.integration

BASE_URL = "http://test"


@pytest.fixture
def celery_eager() -> Any:
    celery_app.conf.task_always_eager = True
    yield celery_app
    celery_app.conf.task_always_eager = False


@pytest.fixture
async def client(redis_cleanup: None, celery_eager: Any) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as c:
        yield c


async def _register_and_login(
    client: httpx.AsyncClient, role: str
) -> dict[str, str]:
    student_id = str(uuid.uuid4().int)[:10]
    staff_id = f"T{uuid.uuid4().int % 100_000_000:08d}"
    identifier = staff_id if role == "teacher" else student_id
    payload: dict[str, Any] = {
        "role": role,
        "email": f"{uuid.uuid4()}@campus.edu.cn",
        "password": "Passw0rd8",
    }
    if role == "teacher":
        payload["staff_id"] = staff_id
    else:
        payload["student_id"] = student_id
    reg = await client.post("/api/v1/auth/register", json=payload)
    assert reg.status_code == 201, reg.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"identifier": identifier, "password": "Passw0rd8"},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return {"token": token}


def _auth(user: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {user['token']}"}


async def test_my_points_requires_auth_and_tracks_teacher_and_student(
    client: httpx.AsyncClient,
) -> None:
    anon = await client.get("/api/v1/users/me/points")
    assert anon.status_code == 401

    teacher = await _register_and_login(client, "teacher")
    student = await _register_and_login(client, "student")
    empty_student = await _register_and_login(client, "student")

    # 无积分学生 → 0 与空流水
    empty_resp = await client.get("/api/v1/users/me/points", headers=_auth(empty_student))
    assert empty_resp.status_code == 200, empty_resp.text
    assert empty_resp.json() == {"balance": 0, "entries": []}

    # 教师首次访问 → 惰性发放 100 且仅一条 grant，重复访问幂等
    t1 = await client.get("/api/v1/users/me/points", headers=_auth(teacher))
    assert t1.status_code == 200, t1.text
    assert t1.json()["balance"] == 100
    assert [e["source"] for e in t1.json()["entries"]] == ["grant"]
    t2 = await client.get("/api/v1/users/me/points", headers=_auth(teacher))
    assert t2.status_code == 200
    assert len(t2.json()["entries"]) == 1

    # 发起悬赏 30 → 余额 70，流水多出 bounty -30
    q_resp = await client.post(
        "/api/v1/questions",
        json={"title": "F07 积分查询测试问题", "body": "测试悬赏冻结与采纳结算流水。"},
        headers=_auth(teacher),
    )
    assert q_resp.status_code == 201, q_resp.text
    qid = q_resp.json()["id"]

    b_resp = await client.post(
        f"/api/v1/questions/{qid}/bounty",
        json={"amount": 30},
        headers=_auth(teacher),
    )
    assert b_resp.status_code == 201, b_resp.text

    t3 = await client.get("/api/v1/users/me/points", headers=_auth(teacher))
    assert t3.status_code == 200
    assert t3.json()["balance"] == 70
    assert [e["delta"] for e in t3.json()["entries"]] == [-30, 100]

    # 学生回答并被采纳 → 学生余额 30，流水含 bounty_award +30
    a_resp = await client.post(
        f"/api/v1/questions/{qid}/answers",
        json={"body": "学生回答，结算悬赏积分。"},
        headers=_auth(student),
    )
    assert a_resp.status_code == 201, a_resp.text
    accept = await client.post(
        f"/api/v1/answers/{a_resp.json()['id']}/accept", headers=_auth(teacher)
    )
    assert accept.status_code == 204, accept.text

    s1 = await client.get("/api/v1/users/me/points", headers=_auth(student))
    assert s1.status_code == 200, s1.text
    assert s1.json()["balance"] == 30
    assert [(e["source"], e["delta"]) for e in s1.json()["entries"]] == [
        ("bounty_award", 30)
    ]
