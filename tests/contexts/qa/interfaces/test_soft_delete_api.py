"""软删除问题与回答接口集成与并发测试（F13）：httpx ASGI + 真 PostgreSQL + 真 Redis。

测试数据遵循真实知识约束，题材取自 PostgreSQL 官方文档：
- https://www.postgresql.org/docs/current/btree-implementation.html
- https://www.postgresql.org/docs/current/routine-vacuuming.html
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.contexts.qa.infrastructure.models import CommentModel, VoteModel
from app.contexts.reputation.infrastructure.celery_app import celery_app
from app.contexts.reputation.infrastructure.models import ReputationLedgerModel
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


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register_and_login(
    client: httpx.AsyncClient, *, role: str = "student"
) -> tuple[str, str]:
    ident = str(uuid.uuid4().int)[:10]
    payload: dict[str, str] = {
        "role": role,
        "email": f"pg-f13-{uuid.uuid4().hex[:10]}@edu.cn",
        "password": "Passw0rd8",
    }
    if role == "student":
        payload["student_id"] = ident
    else:
        payload["staff_id"] = f"T{ident[:7]}"
        ident = payload["staff_id"]

    reg = await client.post("/api/v1/auth/register", json=payload)
    assert reg.status_code == 201, reg.text
    login = await client.post(
        "/api/v1/auth/login",
        json={"identifier": ident, "password": "Passw0rd8"},
    )
    assert login.status_code == 200, login.text
    return str(login.json()["access_token"]), str(reg.json()["id"])


async def _ask(
    client: httpx.AsyncClient,
    token: str,
    *,
    title: str | None = None,
    body: str | None = None,
    tags: list[str] | None = None,
) -> str:
    payload: dict[str, object] = {
        "title": title
        or f"PostgreSQL MVCC 快照隔离与 B-Tree 索引清理机制探讨 #{uuid.uuid4().hex[:6]}",
        "body": body
        or (
            "在 READ COMMITTED 隔离级别下，表堆产生死元组后 VACUUM "
            "如何配合可见性映射回收 B-Tree 索引空间？"
        ),
    }
    if tags is not None:
        payload["tags"] = tags
    resp = await client.post("/api/v1/questions", json=payload, headers=_auth(token))
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def _answer(
    client: httpx.AsyncClient,
    token: str,
    qid: str,
    *,
    body: str | None = None,
) -> str:
    resp = await client.post(
        f"/api/v1/questions/{qid}/answers",
        json={
            "body": body
            or (
                "VACUUM 先扫描未标记 all-visible 的堆页收集死 TID，"
                "再遍历 B-Tree 删除对应索引条目并复用页内空间。"
            )
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def test_delete_question_and_answer_auth_and_status_matrix(
    client: httpx.AsyncClient,
) -> None:
    """D1/D2/D3 状态码矩阵：401 / 403（先于 409）/ 404 / 409 / 204（含重复删幂等与关闭态删除）。"""
    asker_token, _ = await _register_and_login(client)
    answerer_token, _ = await _register_and_login(client)
    other_token, _ = await _register_and_login(client)

    qid = await _ask(client, asker_token)
    aid_unaccepted = await _answer(client, answerer_token, qid)
    aid_accepted = await _answer(
        client,
        answerer_token,
        qid,
        body="HOT（Heap-Only Tuples）在未修改任何索引列且同页空间充足时无需新增 B-Tree 索引项。",
    )

    # 1. 未认证 401
    assert (await client.delete(f"/api/v1/questions/{qid}")).status_code == 401
    assert (await client.delete(f"/api/v1/answers/{aid_unaccepted}")).status_code == 401

    # 2. 不存在 404
    assert (
        await client.delete(
            f"/api/v1/questions/{uuid.uuid4()}", headers=_auth(asker_token)
        )
    ).status_code == 404
    assert (
        await client.delete(
            f"/api/v1/answers/{uuid.uuid4()}", headers=_auth(answerer_token)
        )
    ).status_code == 404

    # 3. 采纳 aid_accepted 后，验证 403 优先于 409，以及作者删除触发 409
    assert (
        await client.post(
            f"/api/v1/answers/{aid_accepted}/accept", headers=_auth(asker_token)
        )
    ).status_code == 204

    # 非作者删已采纳回答 / 已采纳问题 → 403（鉴权优先于状态冲突）
    r_ans_403 = await client.delete(
        f"/api/v1/answers/{aid_accepted}", headers=_auth(asker_token)
    )
    assert r_ans_403.status_code == 403
    assert r_ans_403.json() == {"detail": "仅回答者可删除回答"}

    r_q_403 = await client.delete(
        f"/api/v1/questions/{qid}", headers=_auth(other_token)
    )
    assert r_q_403.status_code == 403
    assert r_q_403.json() == {"detail": "仅提问者可删除问题"}

    # 作者本人删已采纳回答 / 已采纳问题 → 409（D2=B）
    r_ans_409 = await client.delete(
        f"/api/v1/answers/{aid_accepted}", headers=_auth(answerer_token)
    )
    assert r_ans_409.status_code == 409
    assert r_ans_409.json() == {"detail": "已采纳的回答不可删除"}

    r_q_409 = await client.delete(
        f"/api/v1/questions/{qid}", headers=_auth(asker_token)
    )
    assert r_q_409.status_code == 409
    assert r_q_409.json() == {"detail": "该问题已有采纳答案，不可删除"}

    # 4. 同一问题下的未采纳回答仍允许答主本人软删除（204），重复删除仍 204，他人访问 404
    assert (
        await client.delete(
            f"/api/v1/answers/{aid_unaccepted}", headers=_auth(answerer_token)
        )
    ).status_code == 204
    assert (
        await client.delete(
            f"/api/v1/answers/{aid_unaccepted}", headers=_auth(answerer_token)
        )
    ).status_code == 204
    assert (
        await client.delete(
            f"/api/v1/answers/{aid_unaccepted}", headers=_auth(other_token)
        )
    ).status_code == 404

    # 5. D3：已关闭问题下允许答主删回答，也允许提问者删已关闭问题本体
    qid_closed = await _ask(client, asker_token)
    aid_under_closed = await _answer(client, answerer_token, qid_closed)
    assert (
        await client.post(
            f"/api/v1/questions/{qid_closed}/close", headers=_auth(asker_token)
        )
    ).status_code == 204
    assert (
        await client.delete(
            f"/api/v1/answers/{aid_under_closed}", headers=_auth(answerer_token)
        )
    ).status_code == 204
    assert (
        await client.delete(
            f"/api/v1/questions/{qid_closed}", headers=_auth(asker_token)
        )
    ).status_code == 204
    # 作者重复删已删问题幂等 204；非作者对已删问题 404
    assert (
        await client.delete(
            f"/api/v1/questions/{qid_closed}", headers=_auth(asker_token)
        )
    ).status_code == 204
    assert (
        await client.delete(
            f"/api/v1/questions/{qid_closed}", headers=_auth(other_token)
        )
    ).status_code == 404


async def test_soft_delete_filters_all_pipelines_and_updates_badges_and_refunds_bounty(
    client: httpx.AsyncClient,
) -> None:
    """全链路过滤 + 父问题已删后回答隔离（404 非 403）+ 徽章剔除 + 开放悬赏退款只退一次。"""
    asker_token, _ = await _register_and_login(client)
    answerer_token, answerer_id = await _register_and_login(client)
    teacher_token, _ = await _register_and_login(client, role="teacher")
    other_token, _ = await _register_and_login(client)

    tag_key = f"pgmvcc{uuid.uuid4().hex[:4]}"
    search_token = f"VisibilityMap{uuid.uuid4().hex[:6]}"
    q_seed = await _ask(
        client,
        asker_token,
        title=f"{search_token} 存活参照问题：PostgreSQL B-Tree 去重页内结构",
        tags=[tag_key],
    )
    qid = await _ask(
        client,
        asker_token,
        title=f"{search_token} 待软删除问题：VACUUM 如何清理死索引元组",
        tags=[tag_key],
    )
    aid1 = await _answer(client, answerer_token, qid)
    aid2 = await _answer(
        client,
        answerer_token,
        qid,
        body="在 PostgreSQL 14+ 中，B-Tree 叶子页分裂前会先尝试 bottom-up 局部清理死索引项。",
    )

    # 教师对 qid 发起 35 积分悬赏（初始 100 → 余额 65）
    bounty_resp = await client.post(
        f"/api/v1/questions/{qid}/bounty",
        json={"amount": 35},
        headers=_auth(teacher_token),
    )
    assert bounty_resp.status_code == 201, bounty_resp.text
    pts_before = (
        await client.get("/api/v1/users/me/points", headers=_auth(teacher_token))
    ).json()
    assert pts_before["balance"] == 65

    # 删除前徽章统计：answerer 在 qid 下有 2 条回答，1 个活跃日
    badges_before = (await client.get(f"/api/v1/users/{answerer_id}/badges")).json()
    assert badges_before["answer_count"] == 2
    assert badges_before["longest_streak_days"] == 1

    # Step A：先软删单条回答 aid1 → 详情只剩 aid2，answer_count 降为 1
    assert (
        await client.delete(f"/api/v1/answers/{aid1}", headers=_auth(answerer_token))
    ).status_code == 204
    detail_mid = (await client.get(f"/api/v1/questions/{qid}")).json()
    assert [a["id"] for a in detail_mid["answers"]] == [aid2]
    assert (
        await client.get(f"/api/v1/users/{answerer_id}/badges")
    ).json()["answer_count"] == 1

    # 对已删回答 aid1 的写操作（编辑/评论/投票/采纳）全部返回 404
    assert (
        await client.patch(
            f"/api/v1/answers/{aid1}",
            json={"body": "编辑已删回答"},
            headers=_auth(answerer_token),
        )
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/answers/{aid1}/comments",
            json={"body": "评论已删回答"},
            headers=_auth(other_token),
        )
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/questions/{qid}/answers/{aid1}/vote",
            json={"direction": "up"},
            headers=_auth(other_token),
        )
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/answers/{aid1}/accept", headers=_auth(asker_token))
    ).status_code == 404

    # Step B：提问者软删除问题 qid（此时 aid2 自身未单独删）
    assert (
        await client.delete(f"/api/v1/questions/{qid}", headers=_auth(asker_token))
    ).status_code == 204

    # 1. 开放悬赏同事务全额退回教师账户（余额 65 → 100）；作者重复删除问题不二次退款
    pts_after = (
        await client.get("/api/v1/users/me/points", headers=_auth(teacher_token))
    ).json()
    assert pts_after["balance"] == 100
    refund_entries = [
        e for e in pts_after["entries"] if e["source"] == "bounty_refund"
    ]
    assert len(refund_entries) == 1 and refund_entries[0]["delta"] == 35

    assert (
        await client.delete(f"/api/v1/questions/{qid}", headers=_auth(asker_token))
    ).status_code == 204
    pts_repeat = (
        await client.get("/api/v1/users/me/points", headers=_auth(teacher_token))
    ).json()
    assert pts_repeat["balance"] == 100

    # 2. 列表（无参 & 搜索+标签筛选）、详情、相关推荐、悬赏查询全部排除已删问题
    list_filtered = (
        await client.get(
            "/api/v1/questions", params={"q": search_token, "tag": [tag_key]}
        )
    ).json()
    assert list_filtered["total"] == 1
    assert [item["id"] for item in list_filtered["items"]] == [q_seed]

    assert (await client.get(f"/api/v1/questions/{qid}")).status_code == 404
    assert (await client.get(f"/api/v1/questions/{qid}/related")).status_code == 404
    seed_related = (await client.get(f"/api/v1/questions/{q_seed}/related")).json()
    assert qid not in [item["id"] for item in seed_related]
    assert (await client.get(f"/api/v1/questions/{qid}/bounty")).status_code == 404

    # 3. 对已删问题的所有写入口（编辑/关闭/回答/投票/评论/悬赏）一律 404
    assert (
        await client.patch(
            f"/api/v1/questions/{qid}",
            json={"title": "编辑已删问题"},
            headers=_auth(asker_token),
        )
    ).status_code == 404
    assert (
        await client.post(f"/api/v1/questions/{qid}/close", headers=_auth(asker_token))
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/questions/{qid}/answers",
            json={"body": "回答已删问题"},
            headers=_auth(other_token),
        )
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/questions/{qid}/vote",
            json={"direction": "up"},
            headers=_auth(other_token),
        )
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/questions/{qid}/comments",
            json={"body": "评论已删问题"},
            headers=_auth(other_token),
        )
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/questions/{qid}/bounty",
            json={"amount": 10},
            headers=_auth(teacher_token),
        )
    ).status_code == 404

    # 4. D4：对所属问题已删但自身未单独删的回答 aid2，无论作者还是非作者调用
    # PATCH / DELETE / accept / comment / vote 均必须返回 404（绝不返回 403 泄露存在性！）
    for actor_tok in (answerer_token, other_token):
        assert (
            await client.patch(
                f"/api/v1/answers/{aid2}",
                json={"body": "尝试在父问题已删时编辑回答"},
                headers=_auth(actor_tok),
            )
        ).status_code == 404
        assert (
            await client.delete(
                f"/api/v1/answers/{aid2}", headers=_auth(actor_tok)
            )
        ).status_code == 404

    assert (
        await client.post(f"/api/v1/answers/{aid2}/accept", headers=_auth(asker_token))
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/answers/{aid2}/comments",
            json={"body": "父问题已删后对回答评论"},
            headers=_auth(other_token),
        )
    ).status_code == 404
    assert (
        await client.post(
            f"/api/v1/questions/{qid}/answers/{aid2}/vote",
            json={"direction": "up"},
            headers=_auth(other_token),
        )
    ).status_code == 404

    # 5. D5：父问题软删后，answerer 的回答数与历史活跃天数归零
    badges_after = (await client.get(f"/api/v1/users/{answerer_id}/badges")).json()
    assert badges_after["answer_count"] == 0
    assert badges_after["longest_streak_days"] == 0


async def test_concurrent_delete_question_and_accept_or_repeat_delete(
    client: httpx.AsyncClient,
) -> None:
    """并发实证：① 多路并发删含悬赏问题全 204 且恰退一次；② 删问题/删回答 × 采纳严格互斥。"""
    asker_token, _ = await _register_and_login(client)
    answerer_token, _ = await _register_and_login(client)
    teacher_token, _ = await _register_and_login(client, role="teacher")

    # ① 6 路并发删除同一含悬赏问题
    qid_bounty = await _ask(client, asker_token)
    assert (
        await client.post(
            f"/api/v1/questions/{qid_bounty}/bounty",
            json={"amount": 40},
            headers=_auth(teacher_token),
        )
    ).status_code == 201

    del_resps = await asyncio.gather(
        *(
            client.delete(
                f"/api/v1/questions/{qid_bounty}", headers=_auth(asker_token)
            )
            for _ in range(6)
        )
    )
    assert [r.status_code for r in del_resps] == [204] * 6
    pts = (
        await client.get("/api/v1/users/me/points", headers=_auth(teacher_token))
    ).json()
    assert pts["balance"] == 100

    # ② 删问题 × 采纳并发 & 删回答 × 采纳并发
    for mode in ("delete_question", "delete_answer"):
        qid = await _ask(client, asker_token)
        aid = await _answer(client, answerer_token, qid)
        del_coro = (
            client.delete(f"/api/v1/questions/{qid}", headers=_auth(asker_token))
            if mode == "delete_question"
            else client.delete(f"/api/v1/answers/{aid}", headers=_auth(answerer_token))
        )
        del_r, acc_r = await asyncio.gather(
            del_coro,
            client.post(f"/api/v1/answers/{aid}/accept", headers=_auth(asker_token)),
        )
        pair = (del_r.status_code, acc_r.status_code)
        # 要么删除先赢（204, 404），要么采纳先赢（409, 204）
        assert pair in ((204, 404), (409, 204)), pair


async def test_concurrent_delete_answer_and_vote_or_comment_linearization(
    client: httpx.AsyncClient,
) -> None:
    """并发实证（D4 锁父问题后重读 Answer）：删回答 × 投票/评论绝不向已删回答写入脏票/脏评论。"""
    asker_token, _ = await _register_and_login(client)
    answerer_token, answerer_id = await _register_and_login(client)
    voter_token, _ = await _register_and_login(client)

    expected_reputation_rows = 0
    for idx in range(8):
        qid = await _ask(client, asker_token)
        aid = await _answer(client, answerer_token, qid)
        aid_uuid = uuid.UUID(aid)

        if idx % 2 == 0:
            del_r, vote_r, comment_r = await asyncio.gather(
                client.delete(f"/api/v1/answers/{aid}", headers=_auth(answerer_token)),
                client.post(
                    f"/api/v1/questions/{qid}/answers/{aid}/vote",
                    json={"direction": "up"},
                    headers=_auth(voter_token),
                ),
                client.post(
                    f"/api/v1/answers/{aid}/comments",
                    json={"body": "针对 B-Tree 页面 high key 并发校验的讨论"},
                    headers=_auth(voter_token),
                ),
            )
        else:
            vote_r, comment_r, del_r = await asyncio.gather(
                client.post(
                    f"/api/v1/questions/{qid}/answers/{aid}/vote",
                    json={"direction": "up"},
                    headers=_auth(voter_token),
                ),
                client.post(
                    f"/api/v1/answers/{aid}/comments",
                    json={"body": "针对 B-Tree 页面 high key 并发校验的讨论"},
                    headers=_auth(voter_token),
                ),
                client.delete(f"/api/v1/answers/{aid}", headers=_auth(answerer_token)),
            )

        assert del_r.status_code == 204
        assert vote_r.status_code in (204, 404)
        assert comment_r.status_code in (201, 404)

        async with session_factory() as session:
            v_cnt = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(VoteModel)
                        .where(VoteModel.target_id == aid_uuid)
                    )
                ).scalar_one()
            )
            c_cnt = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(CommentModel)
                        .where(CommentModel.target_id == aid_uuid)
                    )
                ).scalar_one()
            )
            rep_cnt = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(ReputationLedgerModel)
                        .where(
                            ReputationLedgerModel.user_id == uuid.UUID(answerer_id)
                        )
                    )
                ).scalar_one()
            )

        if vote_r.status_code == 204:
            expected_reputation_rows += 1
            assert v_cnt == 1
        else:
            # 删除先赢：库内零新票，也不触发声誉入账
            assert v_cnt == 0
        assert rep_cnt == expected_reputation_rows

        if comment_r.status_code == 201:
            assert c_cnt == 1
        else:
            assert c_cnt == 0
