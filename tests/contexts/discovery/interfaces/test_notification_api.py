"""通知接口集成测试（F04）：三类触发、收件人隔离、已读幂等、未读数对账。"""

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


async def _register_and_login(client: httpx.AsyncClient) -> dict[str, str]:
    payload = {
        "role": "student",
        "email": f"{uuid.uuid4()}@stu.edu.cn",
        "password": "Passw0rd8",
        "student_id": str(uuid.uuid4().int)[:10],
    }
    reg = await client.post("/api/v1/auth/register", json=payload)
    assert reg.status_code == 201, reg.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"identifier": payload["student_id"], "password": payload["password"]},
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


async def test_notification_flow_and_isolation(client: httpx.AsyncClient) -> None:
    asker = await _register_and_login(client)
    responder = await _register_and_login(client)

    question = await client.post(
        "/api/v1/questions",
        json={"title": "F04 通知集成测试问题", "body": "验证三类通知触发与收件人隔离。"},
        headers=_auth(asker),
    )
    assert question.status_code == 201, question.text
    question_id = question.json()["id"]

    answer = await client.post(
        f"/api/v1/questions/{question_id}/answers",
        json={"body": "这是 responder 的回答正文。"},
        headers=_auth(responder),
    )
    assert answer.status_code == 201, answer.text
    answer_id = answer.json()["id"]

    # 提问者自评不产生通知
    own_comment = await client.post(
        f"/api/v1/questions/{question_id}/comments",
        json={"body": "提问者自己的补充说明。"},
        headers=_auth(asker),
    )
    assert own_comment.status_code == 201, own_comment.text

    # responder 评论提问者的问题 → 第二条通知
    comment = await client.post(
        f"/api/v1/questions/{question_id}/comments",
        json={"body": "responder 的追问评论。"},
        headers=_auth(responder),
    )
    assert comment.status_code == 201, comment.text

    accept = await client.post(
        f"/api/v1/answers/{answer_id}/accept", headers=_auth(asker)
    )
    assert accept.status_code == 204, accept.text

    # asker 评论 responder 的回答 → responder 应收到带 question_id 的评论通知
    answer_comment = await client.post(
        f"/api/v1/answers/{answer_id}/comments",
        json={"body": "感谢回答，补充问一下细节。"},
        headers=_auth(asker),
    )
    assert answer_comment.status_code == 201, answer_comment.text

    asker_list = await client.get(
        "/api/v1/notifications", params={"page_size": 20}, headers=_auth(asker)
    )
    assert asker_list.status_code == 200, asker_list.text
    data = asker_list.json()
    assert data["total"] == 2
    types = [item["type"] for item in data["items"]]
    assert types == ["comment_created", "answer_posted"]  # 新→旧
    assert {item["actor_id"] for item in data["items"]} == {responder["id"]}
    assert {item["question_id"] for item in data["items"]} == {question_id}

    unread = await client.get(
        "/api/v1/notifications/unread-count", headers=_auth(asker)
    )
    assert unread.status_code == 200, unread.text
    assert unread.json()["count"] == 2

    newest = data["items"][0]["id"]
    mark = await client.post(
        f"/api/v1/notifications/{newest}/read", headers=_auth(asker)
    )
    assert mark.status_code == 204, mark.text
    again = await client.post(
        f"/api/v1/notifications/{newest}/read", headers=_auth(asker)
    )
    assert again.status_code == 204, again.text  # 幂等

    # 他人不可读：responder 标记 asker 的通知 → 404
    other = await client.post(
        f"/api/v1/notifications/{newest}/read", headers=_auth(responder)
    )
    assert other.status_code == 404, other.text

    read_all = await client.post(
        "/api/v1/notifications/read-all", headers=_auth(asker)
    )
    assert read_all.status_code == 200, read_all.text
    assert read_all.json()["updated"] == 1
    unread_after = await client.get(
        "/api/v1/notifications/unread-count", headers=_auth(asker)
    )
    assert unread_after.json()["count"] == 0

    responder_list = await client.get(
        "/api/v1/notifications", headers=_auth(responder)
    )
    assert responder_list.status_code == 200, responder_list.text
    assert responder_list.json()["total"] == 2
    assert [item["type"] for item in responder_list.json()["items"]] == [
        "comment_created",
        "answer_accepted",
    ]
    assert {
        item["question_id"] for item in responder_list.json()["items"]
    } == {question_id}

    anonymous = await client.get("/api/v1/notifications")
    assert anonymous.status_code == 401
