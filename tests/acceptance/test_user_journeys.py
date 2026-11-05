"""验收测试：按用户故事走完整学习闭环（真 PostgreSQL + 真 Redis，httpx ASGI）。

与集成测试的区别：本层只断言"用户看到的结果"，不关心实现细节——
注册登录→提问→回答→投票/评论→采纳→关闭冻结，一个场景一条链路。
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest

from app.main import create_app

pytestmark = pytest.mark.integration

BASE_URL = "http://test"


@pytest.fixture
async def client(redis_cleanup: None) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as c:
        yield c


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register_and_login(client: httpx.AsyncClient, *, role: str) -> tuple[str, str]:
    """注册并登录一个全新用户，返回 (access_token, user_id)。"""
    suffix = uuid.uuid4().hex[:10]
    password = "Passw0rd8"
    payload: dict[str, Any] = {
        "role": role,
        "email": f"acceptance-{suffix}@campus.edu.cn",
        "password": password,
    }
    if role == "student":
        payload["student_id"] = f"20{uuid.uuid4().int}"[:10]
        identifier = payload["student_id"]
    else:
        payload["staff_id"] = f"T{uuid.uuid4().int}"[:8]
        identifier = payload["staff_id"]

    reg = await client.post("/api/v1/auth/register", json=payload)
    assert reg.status_code == 201, reg.text
    login = await client.post(
        "/api/v1/auth/login", json={"identifier": identifier, "password": password}
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    me = await client.get("/api/v1/auth/me", headers=_auth(token))
    assert me.status_code == 200, me.text
    return token, me.json()["id"]


async def _ask_question(client: httpx.AsyncClient, token: str, *, tag: str) -> dict[str, Any]:
    resp = await client.post(
        "/api/v1/questions",
        json={
            "title": f"验收场景：如何在课程项目中落地 {tag} 的工程实践？",
            "body": (
                "我们正在做课程项目，想了解从需求到测试的完整落地步骤，"
                "希望有经验的学长学姐给出建议。"
            ),
            "tags": [tag],
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _answer(client: httpx.AsyncClient, token: str, question_id: str) -> dict[str, Any]:
    resp = await client.post(
        f"/api/v1/questions/{question_id}/answers",
        json={"body": "建议先把验收标准写成场景，再按场景补自动化测试，最后用真实数据跑一遍回归。"},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_student_learning_loop(client: httpx.AsyncClient) -> None:
    """学生提问 → 同学回答 → 投票/评论 → 作者采纳：详情页呈现完整结果。"""
    author_token, _ = await _register_and_login(client, role="student")
    helper_token, _ = await _register_and_login(client, role="student")
    tag = f"验收{uuid.uuid4().hex[:6]}"

    question = await _ask_question(client, author_token, tag=tag)
    answer = await _answer(client, helper_token, question["id"])

    vote = await client.post(
        f"/api/v1/questions/{question['id']}/answers/{answer['id']}/vote",
        json={"direction": "up"},
        headers=_auth(author_token),
    )
    assert vote.status_code == 204, vote.text

    comment = await client.post(
        f"/api/v1/answers/{answer['id']}/comments",
        json={"body": "这条建议很具体，我们准备按这个顺序排迭代。"},
        headers=_auth(author_token),
    )
    assert comment.status_code == 201, comment.text

    accept = await client.post(
        f"/api/v1/answers/{answer['id']}/accept", headers=_auth(author_token)
    )
    assert accept.status_code == 204, accept.text

    detail = await client.get(f"/api/v1/questions/{question['id']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["status"] == "open"
    assert body["accepted_answer_id"] == answer["id"]
    shown = next(a for a in body["answers"] if a["id"] == answer["id"])
    assert shown["is_accepted"] is True
    assert shown["votes"] == 1
    assert [c["body"] for c in shown["comments"]] == ["这条建议很具体，我们准备按这个顺序排迭代。"]


async def test_guest_can_read_but_cannot_write(client: httpx.AsyncClient) -> None:
    """访客可浏览问题/详情/标签；写操作被 401 拒绝。"""
    author_token, _ = await _register_and_login(client, role="student")
    question = await _ask_question(client, author_token, tag=f"验收{uuid.uuid4().hex[:6]}")

    listing = await client.get("/api/v1/questions?page=1&page_size=10")
    assert listing.status_code == 200, listing.text
    assert any(item["id"] == question["id"] for item in listing.json()["items"])

    detail = await client.get(f"/api/v1/questions/{question['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["title"] == question["title"]

    tags = await client.get("/api/v1/tags")
    assert tags.status_code == 200, tags.text

    write = await client.post(
        "/api/v1/questions", json={"title": "访客不该能发的问题", "body": "访客写操作应被拒绝"}
    )
    assert write.status_code == 401, write.text


async def test_closed_question_freezes_interactions(client: httpx.AsyncClient) -> None:
    """作者关闭问题后，回答/评论/投票/采纳/编辑全部被 409 冻结，详情仍可读。"""
    author_token, _ = await _register_and_login(client, role="student")
    helper_token, _ = await _register_and_login(client, role="student")
    question = await _ask_question(client, author_token, tag=f"验收{uuid.uuid4().hex[:6]}")
    answer = await _answer(client, helper_token, question["id"])

    close = await client.post(
        f"/api/v1/questions/{question['id']}/close", headers=_auth(author_token)
    )
    assert close.status_code == 204, close.text

    blocked: list[httpx.Response] = [
        await client.post(
            f"/api/v1/questions/{question['id']}/answers",
            json={"body": "关闭后不应还能回答。"},
            headers=_auth(helper_token),
        ),
        await client.post(
            f"/api/v1/questions/{question['id']}/comments",
            json={"body": "关闭后不应还能评论。"},
            headers=_auth(helper_token),
        ),
        await client.post(
            f"/api/v1/questions/{question['id']}/answers/{answer['id']}/vote",
            json={"direction": "up"},
            headers=_auth(helper_token),
        ),
        await client.post(
            f"/api/v1/answers/{answer['id']}/accept", headers=_auth(author_token)
        ),
        await client.patch(
            f"/api/v1/questions/{question['id']}",
            json={"title": "关闭后不应还能编辑题目"},
            headers=_auth(author_token),
        ),
    ]
    for resp in blocked:
        assert resp.status_code == 409, resp.text

    detail = await client.get(f"/api/v1/questions/{question['id']}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["status"] == "closed"
    assert len(detail.json()["answers"]) == 1
