"""教师悬赏接口集成测试（F07）：权限、余额、唯一悬赏、采纳结算、关闭退款。"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.contexts.qa.infrastructure.models import (
    PointsAccountModel,
    QuestionBountyModel,
    QuestionModel,
)
from app.contexts.reputation.infrastructure.celery_app import celery_app
from app.main import create_app
from app.shared.engine import session_factory

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
    me = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me.status_code == 200, me.text
    return {"token": token, "id": me.json()["id"]}


def _auth(user: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {user['token']}"}


async def _create_question(client: httpx.AsyncClient, user: dict[str, str], title: str) -> str:
    resp = await client.post(
        "/api/v1/questions",
        json={"title": title, "body": "F07 悬赏接口集成：权限、余额、结算与退款。"},
        headers=_auth(user),
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def _balance(user_id: str) -> int:
    async with session_factory() as session:
        value = (
            await session.execute(
                select(PointsAccountModel.balance).where(
                    PointsAccountModel.user_id == uuid.UUID(user_id)
                )
            )
        ).scalar_one_or_none()
        return int(value or 0)


async def test_bounty_permission_balance_and_settlement(
    client: httpx.AsyncClient,
) -> None:
    teacher = await _register_and_login(client, "teacher")
    student = await _register_and_login(client, "student")
    question_id = await _create_question(client, teacher, "F07 悬赏结算问题")

    forbidden = await client.post(
        f"/api/v1/questions/{question_id}/bounty",
        json={"amount": 10},
        headers=_auth(student),
    )
    assert forbidden.status_code == 403, forbidden.text

    created = await client.post(
        f"/api/v1/questions/{question_id}/bounty",
        json={"amount": 30},
        headers=_auth(teacher),
    )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "open"
    assert await _balance(teacher["id"]) == 70

    fetched = await client.get(f"/api/v1/questions/{question_id}/bounty")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["amount"] == 30

    duplicate = await client.post(
        f"/api/v1/questions/{question_id}/bounty",
        json={"amount": 5},
        headers=_auth(teacher),
    )
    assert duplicate.status_code == 409, duplicate.text

    poor_question = await _create_question(client, teacher, "F07 悬赏余额不足问题")
    insufficient = await client.post(
        f"/api/v1/questions/{poor_question}/bounty",
        json={"amount": 1000},
        headers=_auth(teacher),
    )
    assert insufficient.status_code == 409, insufficient.text

    answer = await client.post(
        f"/api/v1/questions/{question_id}/answers",
        json={"body": "学生回答，用于触发悬赏结算。"},
        headers=_auth(student),
    )
    assert answer.status_code == 201, answer.text
    accept = await client.post(
        f"/api/v1/answers/{answer.json()['id']}/accept", headers=_auth(teacher)
    )
    assert accept.status_code == 204, accept.text

    after = await client.get(f"/api/v1/questions/{question_id}/bounty")
    assert after.status_code == 200
    assert after.json() is None  # 已结算，无进行中悬赏
    assert await _balance(student["id"]) == 30


async def test_bounty_refund_on_close(client: httpx.AsyncClient) -> None:
    teacher = await _register_and_login(client, "teacher")
    question_id = await _create_question(client, teacher, "F07 悬赏退款问题")

    created = await client.post(
        f"/api/v1/questions/{question_id}/bounty",
        json={"amount": 20},
        headers=_auth(teacher),
    )
    assert created.status_code == 201, created.text
    assert await _balance(teacher["id"]) == 80

    closed = await client.post(
        f"/api/v1/questions/{question_id}/close", headers=_auth(teacher)
    )
    assert closed.status_code == 204, closed.text
    assert await _balance(teacher["id"]) == 100  # 全额退款


async def test_bounty_missing_question_returns_404(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get(f"/api/v1/questions/{uuid.uuid4()}/bounty")
    assert resp.status_code == 404, resp.text


async def test_bounty_rejected_when_question_already_accepted(
    client: httpx.AsyncClient,
) -> None:
    teacher = await _register_and_login(client, "teacher")
    student = await _register_and_login(client, "student")
    question_id = await _create_question(client, teacher, "F07 已采纳不可悬赏")

    answer = await client.post(
        f"/api/v1/questions/{question_id}/answers",
        json={"body": "学生答案，先采纳后应禁止再发起悬赏。"},
        headers=_auth(student),
    )
    assert answer.status_code == 201, answer.text
    accept = await client.post(
        f"/api/v1/answers/{answer.json()['id']}/accept", headers=_auth(teacher)
    )
    assert accept.status_code == 204, accept.text

    rejected = await client.post(
        f"/api/v1/questions/{question_id}/bounty",
        json={"amount": 20},
        headers=_auth(teacher),
    )
    assert rejected.status_code == 409, rejected.text
    assert await _balance(teacher["id"]) == 0  # 未惰性扣款或开户
    active = await client.get(f"/api/v1/questions/{question_id}/bounty")
    assert active.status_code == 200
    assert active.json() is None


async def test_bounty_create_and_close_race_never_leaves_open_bounty(
    client: httpx.AsyncClient,
) -> None:
    teacher = await _register_and_login(client, "teacher")
    question_id = await _create_question(client, teacher, "F07 并发关闭与悬赏竞态")

    bounty_resp, close_resp = await asyncio.gather(
        client.post(
            f"/api/v1/questions/{question_id}/bounty",
            json={"amount": 25},
            headers=_auth(teacher),
        ),
        client.post(
            f"/api/v1/questions/{question_id}/close",
            headers=_auth(teacher),
        ),
    )
    assert close_resp.status_code == 204, close_resp.text
    assert bounty_resp.status_code in (201, 409), bounty_resp.text

    active = await client.get(f"/api/v1/questions/{question_id}/bounty")
    assert active.status_code == 200
    assert active.json() is None
    if bounty_resp.status_code == 201:
        assert await _balance(teacher["id"]) == 100
    else:
        assert await _balance(teacher["id"]) == 0

    async with session_factory() as session:
        open_count = (
            await session.execute(
                select(func.count())
                .select_from(QuestionBountyModel)
                .where(
                    QuestionBountyModel.question_id == uuid.UUID(question_id),
                    QuestionBountyModel.status == "open",
                )
            )
        ).scalar_one()
        status_val = (
            await session.execute(
                select(QuestionModel.status).where(
                    QuestionModel.id == uuid.UUID(question_id)
                )
            )
        ).scalar_one()
        assert open_count == 0
        assert status_val == "closed"
