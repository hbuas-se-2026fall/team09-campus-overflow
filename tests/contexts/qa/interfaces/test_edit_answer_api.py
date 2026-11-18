"""编辑回答接口集成测试（US-A02 / F12）：httpx ASGI + 真 PostgreSQL + 真 Redis。"""

from __future__ import annotations

import asyncio
import uuid

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


async def _register_and_login(
    client: httpx.AsyncClient, *, nickname: str | None = None
) -> tuple[str, str]:
    student_id = str(uuid.uuid4().int)[:10]
    payload = {
        "role": "student",
        "email": f"{uuid.uuid4()}@stu.edu.cn",
        "password": "Passw0rd8",
        "student_id": student_id,
    }
    reg = await client.post("/api/v1/auth/register", json=payload)
    assert reg.status_code == 201, reg.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"identifier": student_id, "password": "Passw0rd8"},
    )
    assert login.status_code == 200, login.text
    token = str(login.json()["access_token"])
    user_id = str(reg.json()["id"])
    if nickname is not None:
        patch = await client.patch(
            "/api/v1/auth/me/profile",
            json={"nickname": nickname},
            headers=_auth(token),
        )
        assert patch.status_code == 200, patch.text
    return token, user_id


async def _ask(client: httpx.AsyncClient, token: str) -> str:
    resp = await client.post(
        "/api/v1/questions",
        json={"title": f"编辑回答问题 {uuid.uuid4().hex[:6]}", "body": "问题正文"},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def _answer(client: httpx.AsyncClient, token: str, qid: str, body: str = "初始回答") -> str:
    resp = await client.post(
        f"/api/v1/questions/{qid}/answers",
        json={"body": body},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def test_edit_answer_returns_200_with_votes_comments_and_author_names(
    client: httpx.AsyncClient,
) -> None:
    asker_token, _ = await _register_and_login(client, nickname="提问者")
    author_token, author_id = await _register_and_login(client, nickname="原答主")
    commenter_token, commenter_id = await _register_and_login(client, nickname="评论同学")

    qid = await _ask(client, asker_token)
    aid = await _answer(client, author_token, qid, "初始回答正文")

    # 投票 + 评论 + 采纳
    assert (
        await client.post(
            f"/api/v1/questions/{qid}/answers/{aid}/vote",
            json={"direction": "up"},
            headers=_auth(asker_token),
        )
    ).status_code == 204
    c_resp = await client.post(
        f"/api/v1/answers/{aid}/comments",
        json={"body": "一条已有评论"},
        headers=_auth(commenter_token),
    )
    assert c_resp.status_code == 201
    cid = str(c_resp.json()["id"])
    assert (
        await client.post(f"/api/v1/answers/{aid}/accept", headers=_auth(asker_token))
    ).status_code == 204

    # 已采纳回答仍可编辑（所属问题必为 open）
    resp = await client.patch(
        f"/api/v1/answers/{aid}",
        json={"body": "  补充完善后的回答正文  "},
        headers=_auth(author_token),
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert set(data.keys()) == {
        "id",
        "body",
        "author_id",
        "author_name",
        "created_at",
        "votes",
        "is_accepted",
        "comments",
    }
    assert data["id"] == aid
    assert data["body"] == "补充完善后的回答正文"
    assert data["author_id"] == author_id
    assert data["author_name"] == "原答主"
    assert data["votes"] == 1
    assert data["is_accepted"] is True
    assert len(data["comments"]) == 1
    assert data["comments"][0]["id"] == cid
    assert data["comments"][0]["author_id"] == commenter_id
    assert data["comments"][0]["author_name"] == "评论同学"

    # 详情页同步反映新正文
    detail = (await client.get(f"/api/v1/questions/{qid}")).json()
    assert detail["answers"][0]["body"] == "补充完善后的回答正文"
    assert detail["answers"][0]["is_accepted"] is True


async def test_edit_answer_auth_and_error_matrix(client: httpx.AsyncClient) -> None:
    asker_token, _ = await _register_and_login(client)
    author_token, _ = await _register_and_login(client)
    other_token, _ = await _register_and_login(client)

    qid = await _ask(client, asker_token)
    aid = await _answer(client, author_token, qid, "初始回答")

    # 401 未登录
    assert (
        await client.patch(f"/api/v1/answers/{aid}", json={"body": "匿名编辑"})
    ).status_code == 401

    # 403 非回答者（包含提问者）
    for token in (asker_token, other_token):
        r403 = await client.patch(
            f"/api/v1/answers/{aid}",
            json={"body": "越权修改"},
            headers=_auth(token),
        )
        assert r403.status_code == 403
        assert r403.json() == {"detail": "仅回答者可编辑回答"}

    # 404 不存在
    r404 = await client.patch(
        f"/api/v1/answers/{uuid.uuid4()}",
        json={"body": "不存在"},
        headers=_auth(author_token),
    )
    assert r404.status_code == 404

    # 422 校验家族（空串、纯空白、超长、NUL、extra=forbid）
    for bad_payload in (
        {},
        {"body": ""},
        {"body": "   "},
        {"body": "答" * 5001},
        {"body": "bad\x00text"},
        {"body": "正常", "is_accepted": True},
    ):
        assert (
            await client.patch(
                f"/api/v1/answers/{aid}",
                json=bad_payload,
                headers=_auth(author_token),
            )
        ).status_code == 422

    # 409 问题关闭后不可编辑回答
    assert (
        await client.post(f"/api/v1/questions/{qid}/close", headers=_auth(asker_token))
    ).status_code == 204
    r409 = await client.patch(
        f"/api/v1/answers/{aid}",
        json={"body": "关闭后编辑"},
        headers=_auth(author_token),
    )
    assert r409.status_code == 409


async def test_concurrent_edit_answer_and_close_question_linearization(
    client: httpx.AsyncClient,
) -> None:
    """并发竞态实证：覆写两种合法线性化顺序，绝不出现“问题已关闭却落入未预期编辑”的撕裂态。"""
    asker_token, _ = await _register_and_login(client)
    author_token, _ = await _register_and_login(client)

    for idx in range(6):
        qid = await _ask(client, asker_token)
        aid = await _answer(client, author_token, qid, f"原始正文-{idx}")
        new_body = f"并发新正文-{idx}"

        edit_resp, close_resp = await asyncio.gather(
            client.patch(
                f"/api/v1/answers/{aid}",
                json={"body": new_body},
                headers=_auth(author_token),
            ),
            client.post(f"/api/v1/questions/{qid}/close", headers=_auth(asker_token)),
        )
        assert close_resp.status_code == 204
        assert edit_resp.status_code in (200, 409)

        detail = (await client.get(f"/api/v1/questions/{qid}")).json()
        assert detail["status"] == "closed"
        saved_body = detail["answers"][0]["body"]
        if edit_resp.status_code == 200:
            # 线性化顺序 1：edit 先拿锁提交 → close 后到成功，最终 closed 且为新正文
            assert saved_body == new_body
        else:
            # 线性化顺序 2：close 先拿锁提交 → edit 后到 409，最终 closed 且为旧正文
            assert saved_body == f"原始正文-{idx}"
