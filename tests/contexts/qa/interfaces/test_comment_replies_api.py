"""评论二级回复接口集成与并发测试（F14）：httpx ASGI + 真 PostgreSQL + 真 Redis。

测试数据遵循真实知识约束，题材取自课程真实知识点与官方文档：
- Operating Systems: Three Easy Pieces（锁、条件变量与死锁避免）：https://pages.cs.wisc.edu/~remzi/OSTEP/
- PostgreSQL Concurrency Control（行锁与 MVCC）：https://www.postgresql.org/docs/current/mvcc.html
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
from sqlalchemy import func, select

from app.contexts.qa.infrastructure.models import CommentModel
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


async def _register_and_login(client: httpx.AsyncClient) -> tuple[str, str]:
    ident = str(uuid.uuid4().int)[:10]
    payload = {
        "role": "student",
        "email": f"f14-api-{uuid.uuid4().hex[:10]}@edu.cn",
        "password": "Passw0rd8",
        "student_id": ident,
    }
    reg = await client.post("/api/v1/auth/register", json=payload)
    assert reg.status_code == 201, reg.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"identifier": ident, "password": "Passw0rd8"},
    )
    assert login.status_code == 200, login.text
    return str(login.json()["access_token"]), str(reg.json()["id"])


async def _ask(client: httpx.AsyncClient, token: str, *, title: str | None = None) -> str:
    resp = await client.post(
        "/api/v1/questions",
        json={
            "title": title
            or f"操作系统条件变量为何必须配合 while 循环而非 if 检查条件？#{uuid.uuid4().hex[:6]}",
            "body": (
                "在 POSIX pthread 条件变量使用中，教材要求 pthread_cond_wait 放在 while 循环里，"
                "Mesa 语义与虚假唤醒（spurious wakeup）分别会带来什么竞态风险？"
            ),
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def _answer(client: httpx.AsyncClient, token: str, qid: str) -> str:
    resp = await client.post(
        f"/api/v1/questions/{qid}/answers",
        json={
            "body": (
                "Mesa 语义下，被 signal 唤醒的线程只进入就绪队列而非立即持锁运行，"
                "在其重新获得互斥锁之前，其他线程可能已经消费掉共享状态；"
                "同时操作系统内核也允许虚假唤醒，因此必须用 while 重新校验谓词。"
            )
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def _comment_q(
    client: httpx.AsyncClient,
    token: str,
    qid: str,
    body: str,
    *,
    parent_id: str | None = None,
) -> httpx.Response:
    payload: dict[str, object] = {"body": body}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    return await client.post(
        f"/api/v1/questions/{qid}/comments", json=payload, headers=_auth(token)
    )


async def _comment_a(
    client: httpx.AsyncClient,
    token: str,
    aid: str,
    body: str,
    *,
    parent_id: str | None = None,
) -> httpx.Response:
    payload: dict[str, object] = {"body": body}
    if parent_id is not None:
        payload["parent_id"] = parent_id
    return await client.post(
        f"/api/v1/answers/{aid}/comments", json=payload, headers=_auth(token)
    )


async def test_question_and_answer_comment_replies_validation_matrix(
    client: httpx.AsyncClient,
) -> None:
    """D1/D2 完整矩阵：题评/答评二级回复、平铺顺序、404、跨宿主/三级 422、自回复与关贴/软删隔离。"""
    asker_tok, _ = await _register_and_login(client)
    answerer_tok, _ = await _register_and_login(client)
    other_tok, _ = await _register_and_login(client)

    q1 = await _ask(client, asker_tok)
    q2 = await _ask(
        client,
        asker_tok,
        title=f"PostgreSQL 悲观锁 SELECT FOR UPDATE 行锁语义 #{uuid.uuid4().hex[:6]}",
    )
    a1 = await _answer(client, answerer_tok, q1)

    # 1. 题评一级 + 二级回复 + 自己回复自己的一级评论
    q_root_r = await _comment_q(
        client, answerer_tok, q1, "Hoare 语义与 Mesa 语义的主要区别是什么？"
    )
    assert q_root_r.status_code == 201, q_root_r.text
    q_root = q_root_r.json()
    assert q_root["parent_id"] is None

    q_reply_r = await _comment_q(
        client,
        other_tok,
        q1,
        "Hoare 语义在 signal 时立即将锁与 CPU 转交给等待线程，实现成本高。",
        parent_id=q_root["id"],
    )
    assert q_reply_r.status_code == 201, q_reply_r.text
    q_reply = q_reply_r.json()
    assert q_reply["parent_id"] == q_root["id"]

    # 允许回复自己的一级评论
    self_reply_r = await _comment_q(
        client,
        answerer_tok,
        q1,
        "补充：OSTEP 第 30 章也提到几乎所有现代系统都采用 Mesa 语义。",
        parent_id=q_root["id"],
    )
    assert self_reply_r.status_code == 201, self_reply_r.text
    assert self_reply_r.json()["parent_id"] == q_root["id"]

    # 2. 答评一级 + 二级回复
    a_root_r = await _comment_a(client, other_tok, a1, "多生产者多消费者场景是否需要两个条件变量？")
    assert a_root_r.status_code == 201, a_root_r.text
    a_root = a_root_r.json()
    assert a_root["parent_id"] is None

    a_reply_r = await _comment_a(
        client,
        answerer_tok,
        a1,
        "需要 empty 与 fill 两个条件变量，避免消费者唤醒另一个消费者导致死锁。",
        parent_id=a_root["id"],
    )
    assert a_reply_r.status_code == 201, a_reply_r.text
    a_reply = a_reply_r.json()
    assert a_reply["parent_id"] == a_root["id"]

    # 3. 详情与编辑回答响应均为平铺返回且按时间正序携带 parent_id
    detail = (await client.get(f"/api/v1/questions/{q1}")).json()
    assert [c["id"] for c in detail["comments"]] == [
        q_root["id"],
        q_reply["id"],
        self_reply_r.json()["id"],
    ]
    assert [c["parent_id"] for c in detail["comments"]] == [None, q_root["id"], q_root["id"]]

    ans_comments = detail["answers"][0]["comments"]
    assert [c["id"] for c in ans_comments] == [a_root["id"], a_reply["id"]]
    assert [c["parent_id"] for c in ans_comments] == [None, a_root["id"]]

    edited = await client.patch(
        f"/api/v1/answers/{a1}",
        json={"body": "更新回答：必须用 while 循环重新检查条件，并为生产者/消费者拆分条件变量。"},
        headers=_auth(answerer_tok),
    )
    assert edited.status_code == 200, edited.text
    assert [c["parent_id"] for c in edited.json()["comments"]] == [None, a_root["id"]]

    # 4. 校验失败路径：父评论不存在 404 / 跨宿主 422 / 三级回复 422 / extra=forbid 422
    missing_r = await _comment_q(
        client, other_tok, q1, "回复不存在的父评论", parent_id=str(uuid.uuid4())
    )
    assert missing_r.status_code == 404
    assert missing_r.json() == {"detail": "评论不存在"}

    cross_q_r = await _comment_q(
        client, other_tok, q2, "把 q1 评论当 q2 父评论", parent_id=q_root["id"]
    )
    assert cross_q_r.status_code == 422
    assert cross_q_r.json() == {"detail": "父评论不属于当前对象"}

    cross_type_r = await _comment_a(
        client, other_tok, a1, "把题评当答评父评论", parent_id=q_root["id"]
    )
    assert cross_type_r.status_code == 422
    assert cross_type_r.json() == {"detail": "父评论不属于当前对象"}

    third_q_r = await _comment_q(
        client, other_tok, q1, "试图回复二级题评", parent_id=q_reply["id"]
    )
    assert third_q_r.status_code == 422
    assert third_q_r.json() == {"detail": "评论仅支持二级回复，不可回复二级评论"}

    third_a_r = await _comment_a(
        client, other_tok, a1, "试图回复二级答评", parent_id=a_reply["id"]
    )
    assert third_a_r.status_code == 422
    assert third_a_r.json() == {"detail": "评论仅支持二级回复，不可回复二级评论"}

    extra_r = await client.post(
        f"/api/v1/questions/{q1}/comments",
        json={"body": "非法多余字段", "parent_id": q_root["id"], "depth": 2},
        headers=_auth(other_tok),
    )
    assert extra_r.status_code == 422

    # 5. 已关闭问题禁止二级回复 → 409
    assert (
        await client.post(f"/api/v1/questions/{q1}/close", headers=_auth(asker_tok))
    ).status_code == 204
    closed_q_reply = await _comment_q(
        client, other_tok, q1, "关贴后题评二级回复", parent_id=q_root["id"]
    )
    assert closed_q_reply.status_code == 409
    closed_a_reply = await _comment_a(
        client, other_tok, a1, "关贴后答评二级回复", parent_id=a_root["id"]
    )
    assert closed_a_reply.status_code == 409

    # 6. F13 软删联动：软删回答/问题后一二级评论全隐藏且不可再回复（404）
    assert (
        await client.delete(f"/api/v1/answers/{a1}", headers=_auth(answerer_tok))
    ).status_code == 204
    assert (
        await _comment_a(client, other_tok, a1, "对已删回答二级回复", parent_id=a_root["id"])
    ).status_code == 404
    detail_after_ans_del = (await client.get(f"/api/v1/questions/{q1}")).json()
    assert detail_after_ans_del["answers"] == []

    assert (
        await client.delete(f"/api/v1/questions/{q1}", headers=_auth(asker_tok))
    ).status_code == 204
    assert (await client.get(f"/api/v1/questions/{q1}")).status_code == 404
    assert (
        await _comment_q(client, other_tok, q1, "对已删问题二级回复", parent_id=q_root["id"])
    ).status_code == 404


async def test_comment_reply_notifications_and_deduplication(
    client: httpx.AsyncClient,
) -> None:
    """D4 通知端到端实证：三方双发、同人去重只发 1 条 comment_replied、自操作跳过。"""
    asker_tok, _ = await _register_and_login(client)
    commenter_tok, commenter_id = await _register_and_login(client)
    replier_tok, replier_id = await _register_and_login(client)

    qid = await _ask(client, asker_tok)

    # 场景 1：commenter 发一级题评（asker 收到 1 条 comment_created）
    c1 = (await _comment_q(client, commenter_tok, qid, "如何避免持有锁时调用信号？")).json()

    # replier 回复 c1 → commenter 收 comment_replied(comment, c1.id)，
    # asker 收 comment_created(question, qid)
    r1 = await _comment_q(
        client,
        replier_tok,
        qid,
        "持锁发信号可防止唤醒丢失，解锁前发通常更安全。",
        parent_id=c1["id"],
    )
    assert r1.status_code == 201, r1.text

    c_notifs = (
        await client.get("/api/v1/notifications", headers=_auth(commenter_tok))
    ).json()
    assert c_notifs["total"] == 1
    assert c_notifs["items"][0]["type"] == "comment_replied"
    assert c_notifs["items"][0]["target_type"] == "comment"
    assert c_notifs["items"][0]["target_id"] == c1["id"]
    assert c_notifs["items"][0]["actor_id"] == replier_id
    assert c_notifs["items"][0]["question_id"] == qid

    a_notifs = (
        await client.get("/api/v1/notifications", headers=_auth(asker_tok))
    ).json()
    assert a_notifs["total"] == 2
    assert [n["type"] for n in a_notifs["items"]] == ["comment_created", "comment_created"]
    assert {n["actor_id"] for n in a_notifs["items"]} == {commenter_id, replier_id}

    # 场景 2：宿主作者发一级评（0 通知），replier 回复 → 仅新增 1 条 comment_replied（去重）
    c_asker = (await _comment_q(client, asker_tok, qid, "补充：也可参考 futex 实现细节。")).json()
    r2 = await _comment_q(
        client,
        replier_tok,
        qid,
        "Linux futex 在用户态无竞争时不陷入内核。",
        parent_id=c_asker["id"],
    )
    assert r2.status_code == 201, r2.text

    a_notifs_after = (
        await client.get("/api/v1/notifications", headers=_auth(asker_tok))
    ).json()
    assert a_notifs_after["total"] == 3  # 仅增加 1 条而非 2 条
    assert a_notifs_after["items"][0]["type"] == "comment_replied"
    assert a_notifs_after["items"][0]["target_type"] == "comment"
    assert a_notifs_after["items"][0]["target_id"] == c_asker["id"]
    assert a_notifs_after["items"][0]["question_id"] == qid

    # 场景 3：asker 回复自己的一级题评 → 自操作跳过，通知总数仍为 3
    r3 = await _comment_q(
        client, asker_tok, qid, "自回复补充说明", parent_id=c_asker["id"]
    )
    assert r3.status_code == 201
    a_notifs_self = (
        await client.get("/api/v1/notifications", headers=_auth(asker_tok))
    ).json()
    assert a_notifs_self["total"] == 3


async def test_concurrent_reply_vs_close_delete_question_and_delete_answer(
    client: httpx.AsyncClient,
) -> None:
    """D3 并发实证（双顺序）：关贴×二级回复、删题×二级回复、删答×二级回复严格线性化。"""
    asker_tok, _ = await _register_and_login(client)
    answerer_tok, _ = await _register_and_login(client)
    replier_tok, _ = await _register_and_login(client)

    # 1. 关贴 × 题评二级回复（4 轮交替序）
    for idx in range(4):
        qid = await _ask(client, asker_tok)
        root_id = (await _comment_q(client, answerer_tok, qid, "关贴并发一级评")).json()["id"]
        close_coro = client.post(f"/api/v1/questions/{qid}/close", headers=_auth(asker_tok))
        reply_coro = _comment_q(client, replier_tok, qid, "并发二级回复", parent_id=root_id)
        if idx % 2 == 0:
            close_r, reply_r = await asyncio.gather(close_coro, reply_coro)
        else:
            reply_r, close_r = await asyncio.gather(reply_coro, close_coro)
        assert close_r.status_code == 204
        assert reply_r.status_code in (201, 409)
        async with session_factory() as session:
            cnt = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(CommentModel)
                        .where(CommentModel.parent_id == uuid.UUID(root_id))
                    )
                ).scalar_one()
            )
        assert cnt == (1 if reply_r.status_code == 201 else 0)

    # 2. 删题 × 题评二级回复（4 轮交替序）
    for idx in range(4):
        qid = await _ask(client, asker_tok)
        root_id = (await _comment_q(client, answerer_tok, qid, "删题并发一级评")).json()["id"]
        del_coro = client.delete(f"/api/v1/questions/{qid}", headers=_auth(asker_tok))
        reply_coro = _comment_q(client, replier_tok, qid, "删题并发二级回复", parent_id=root_id)
        if idx % 2 == 0:
            del_r, reply_r = await asyncio.gather(del_coro, reply_coro)
        else:
            reply_r, del_r = await asyncio.gather(reply_coro, del_coro)
        assert del_r.status_code == 204
        assert reply_r.status_code in (201, 404)
        async with session_factory() as session:
            cnt = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(CommentModel)
                        .where(CommentModel.parent_id == uuid.UUID(root_id))
                    )
                ).scalar_one()
            )
        assert cnt == (1 if reply_r.status_code == 201 else 0)

    # 3. 删答 × 答评二级回复（4 轮交替序）
    for idx in range(4):
        qid = await _ask(client, asker_tok)
        aid = await _answer(client, answerer_tok, qid)
        root_id = (await _comment_a(client, asker_tok, aid, "删答并发一级评")).json()["id"]
        del_coro = client.delete(f"/api/v1/answers/{aid}", headers=_auth(answerer_tok))
        reply_coro = _comment_a(client, replier_tok, aid, "删答并发二级回复", parent_id=root_id)
        if idx % 2 == 0:
            del_r, reply_r = await asyncio.gather(del_coro, reply_coro)
        else:
            reply_r, del_r = await asyncio.gather(reply_coro, del_coro)
        assert del_r.status_code == 204
        assert reply_r.status_code in (201, 404)
        async with session_factory() as session:
            cnt = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(CommentModel)
                        .where(CommentModel.parent_id == uuid.UUID(root_id))
                    )
                ).scalar_one()
            )
        assert cnt == (1 if reply_r.status_code == 201 else 0)
