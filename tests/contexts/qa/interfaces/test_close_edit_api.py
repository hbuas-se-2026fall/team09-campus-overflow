"""关闭/编辑问题接口集成测试（迭代 5，US-Q08/V02）：httpx ASGI + 真 PostgreSQL + 真 Redis。

覆盖：关闭 204 / 401 / 403 / 404 / 409（重复关闭、已采纳不可关闭）；
编辑 200 / 401 / 403 / 404 / 409 / 422（PATCH 部分更新、extra=forbid）；
关闭=终态（全冻结：禁投题/禁投答/禁回答/禁评论题/禁评论答/禁采纳/禁编辑）。
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.contexts.qa.infrastructure.models import AnswerModel, CommentModel, VoteModel
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


async def _register_and_login(client: httpx.AsyncClient) -> tuple[str, str]:
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
    me = await client.get("/api/v1/auth/me", headers=_auth(token))
    assert me.status_code == 200, me.text
    return token, me.json()["id"]


async def _ask(
    client: httpx.AsyncClient, token: str, *, tags: list[str] | None = None
) -> str:
    body: dict[str, object] = {
        "title": f"关闭编辑 {uuid.uuid4().hex[:8]}",
        "body": "原始正文",
    }
    if tags is not None:
        body["tags"] = tags
    r = await client.post("/api/v1/questions", json=body, headers=_auth(token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _answer(client: httpx.AsyncClient, token: str, qid: str) -> str:
    r = await client.post(
        f"/api/v1/questions/{qid}/answers", json={"body": "回答"}, headers=_auth(token)
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _close(client: httpx.AsyncClient, token: str, qid: str) -> httpx.Response:
    return await client.post(f"/api/v1/questions/{qid}/close", headers=_auth(token))


# ---------------- 关闭 ----------------

async def test_close_returns_204_then_reclose_409(client: httpx.AsyncClient) -> None:
    token, _ = await _register_and_login(client)
    qid = await _ask(client, token)

    resp = await _close(client, token, qid)
    assert resp.status_code == 204, resp.text
    assert resp.content == b""

    r2 = await _close(client, token, qid)
    assert r2.status_code == 409  # 重复关闭（含状态已持久化的实证）

    detail = await client.get(f"/api/v1/questions/{qid}")
    assert detail.status_code == 200  # 已关闭问题详情仍可读
    assert detail.json()["id"] == qid
    assert detail.json()["status"] == "closed"

    listing = await client.get("/api/v1/questions", params={"page": 1, "page_size": 100})
    listed_question = next(item for item in listing.json()["items"] if item["id"] == qid)
    assert listed_question["status"] == "closed"


async def test_close_requires_login_and_valid_id(client: httpx.AsyncClient) -> None:
    token, _ = await _register_and_login(client)
    qid = await _ask(client, token)
    assert (await client.post(f"/api/v1/questions/{qid}/close")).status_code == 401
    r = await client.post(
        f"/api/v1/questions/{uuid.uuid4()}/close", headers=_auth(token)
    )
    assert r.status_code == 404


async def test_close_by_non_author_403_and_still_open(client: httpx.AsyncClient) -> None:
    author_token, _ = await _register_and_login(client)
    other_token, _ = await _register_and_login(client)
    qid = await _ask(client, author_token)

    resp = await _close(client, other_token, qid)
    assert resp.status_code == 403

    # 未关闭：他人仍可投票（状态未被误改）
    vote = await client.post(
        f"/api/v1/questions/{qid}/vote",
        json={"direction": "up"},
        headers=_auth(other_token),
    )
    assert vote.status_code == 204


async def test_close_with_accepted_answer_409(client: httpx.AsyncClient) -> None:
    token, _ = await _register_and_login(client)
    qid = await _ask(client, token)
    aid = await _answer(client, token, qid)
    accept = await client.post(f"/api/v1/answers/{aid}/accept", headers=_auth(token))
    assert accept.status_code == 204

    resp = await _close(client, token, qid)
    assert resp.status_code == 409  # 不变式 5：已采纳答案的问题不可关闭


async def test_closed_question_freezes_all_interactions(client: httpx.AsyncClient) -> None:
    """全冻结（2026-09-29 裁定）：关闭后题票/答票/回答/题评/答评/采纳/编辑一律 409。"""
    author_token, _ = await _register_and_login(client)
    other_token, _ = await _register_and_login(client)
    qid = await _ask(client, author_token)
    aid = await _answer(client, other_token, qid)
    assert (await _close(client, author_token, qid)).status_code == 204

    assert (
        await client.post(
            f"/api/v1/questions/{qid}/vote",
            json={"direction": "up"},
            headers=_auth(other_token),
        )
    ).status_code == 409
    assert (
        await client.post(
            f"/api/v1/questions/{qid}/answers/{aid}/vote",
            json={"direction": "up"},
            headers=_auth(author_token),
        )
    ).status_code == 409
    assert (
        await client.post(
            f"/api/v1/questions/{qid}/answers",
            json={"body": "再来一答"},
            headers=_auth(other_token),
        )
    ).status_code == 409
    assert (
        await client.post(
            f"/api/v1/questions/{qid}/comments",
            json={"body": "题评"},
            headers=_auth(other_token),
        )
    ).status_code == 409
    assert (
        await client.post(
            f"/api/v1/answers/{aid}/comments",
            json={"body": "答评"},
            headers=_auth(author_token),
        )
    ).status_code == 409
    assert (
        await client.post(f"/api/v1/answers/{aid}/accept", headers=_auth(author_token))
    ).status_code == 409
    assert (
        await client.patch(
            f"/api/v1/questions/{qid}",
            json={"title": "试图编辑"},
            headers=_auth(author_token),
        )
    ).status_code == 409

    # 终态未被污染：票数/评论数仍为空
    detail = (await client.get(f"/api/v1/questions/{qid}")).json()
    assert detail["answers"][0]["votes"] == 0
    assert detail["answers"][0]["comments"] == []
    assert detail["comments"] == []


async def test_vote_before_close_ok_then_after_close_409(client: httpx.AsyncClient) -> None:
    author_token, _ = await _register_and_login(client)
    voter_token, _ = await _register_and_login(client)
    qid = await _ask(client, author_token)
    assert (
        await client.post(
            f"/api/v1/questions/{qid}/vote",
            json={"direction": "up"},
            headers=_auth(voter_token),
        )
    ).status_code == 204
    assert (await _close(client, author_token, qid)).status_code == 204
    assert (
        await client.post(
            f"/api/v1/questions/{qid}/vote",
            json={"direction": "up"},
            headers=_auth(voter_token),
        )
    ).status_code == 409


# ---------------- 编辑 ----------------

async def test_edit_patch_partial_and_full(client: httpx.AsyncClient) -> None:
    token, user_id = await _register_and_login(client)
    qid = await _ask(client, token, tags=["数据库"])

    # 只改标题：正文与标签保持
    r1 = await client.patch(
        f"/api/v1/questions/{qid}", json={"title": "  改后标题  "}, headers=_auth(token)
    )
    assert r1.status_code == 200, r1.text
    b1 = r1.json()
    assert b1["title"] == "改后标题"  # strip 端到端
    assert b1["body"] == "原始正文"
    assert b1["tags"] == ["数据库"]
    assert b1["author_id"] == user_id

    # 只改正文：标题保持
    r2 = await client.patch(
        f"/api/v1/questions/{qid}", json={"body": "改后正文"}, headers=_auth(token)
    )
    assert r2.status_code == 200, r2.text
    assert r2.json()["title"] == "改后标题"
    assert r2.json()["body"] == "改后正文"

    # 全量改：详情读到最新值
    r3 = await client.patch(
        f"/api/v1/questions/{qid}",
        json={"title": "终版标题", "body": "终版正文"},
        headers=_auth(token),
    )
    assert r3.status_code == 200
    detail = (await client.get(f"/api/v1/questions/{qid}")).json()
    assert detail["title"] == "终版标题"
    assert detail["body"] == "终版正文"
    assert detail["tags"] == ["数据库"]


async def test_edit_by_non_author_403(client: httpx.AsyncClient) -> None:
    author_token, _ = await _register_and_login(client)
    other_token, _ = await _register_and_login(client)
    qid = await _ask(client, author_token)

    resp = await client.patch(
        f"/api/v1/questions/{qid}", json={"title": "他人改"}, headers=_auth(other_token)
    )
    assert resp.status_code == 403
    detail = (await client.get(f"/api/v1/questions/{qid}")).json()
    assert detail["title"] != "他人改"


async def test_edit_requires_login_and_valid_id(client: httpx.AsyncClient) -> None:
    token, _ = await _register_and_login(client)
    qid = await _ask(client, token)
    assert (
        await client.patch(f"/api/v1/questions/{qid}", json={"title": "未登录"})
    ).status_code == 401
    r = await client.patch(
        f"/api/v1/questions/{uuid.uuid4()}", json={"title": "不存在"}, headers=_auth(token)
    )
    assert r.status_code == 404


async def test_edit_validation_422_family(client: httpx.AsyncClient) -> None:
    token, _ = await _register_and_login(client)
    qid = await _ask(client, token)

    # 空对象（至少一个字段）、空白标题、超长标题、多余字段
    assert (
        await client.patch(f"/api/v1/questions/{qid}", json={}, headers=_auth(token))
    ).status_code == 422
    assert (
        await client.patch(
            f"/api/v1/questions/{qid}", json={"title": "   "}, headers=_auth(token)
        )
    ).status_code == 422
    assert (
        await client.patch(
            f"/api/v1/questions/{qid}", json={"title": "题" * 101}, headers=_auth(token)
        )
    ).status_code == 422
    assert (
        await client.patch(
            f"/api/v1/questions/{qid}",
            json={"title": "x", "author_id": str(uuid.uuid4())},
            headers=_auth(token),
        )
    ).status_code == 422  # extra=forbid 冒名封死


# ---------------- 并发兜底（迭代 5 条件 UPDATE，库级） ----------------


async def test_concurrent_double_close_exactly_one_204(client: httpx.AsyncClient) -> None:
    """并发重复关闭：条件 UPDATE 兜底——恰 1×204 + 其余 409（无多路 204）。"""
    token, _ = await _register_and_login(client)
    qid = await _ask(client, token)

    responses = await asyncio.gather(*(_close(client, token, qid) for _ in range(8)))
    codes = sorted(r.status_code for r in responses)
    assert codes.count(204) == 1, codes
    assert codes.count(409) == 7, codes


async def test_concurrent_close_vs_accept_invariant(client: httpx.AsyncClient) -> None:
    """关闭 × 采纳并发：恰一路成功；终态须守住 Q08×V03 不变式（已采纳不可关闭）。"""
    token, _ = await _register_and_login(client)
    qid = await _ask(client, token)
    aid = await _answer(client, token, qid)

    close_resp, accept_resp = await asyncio.gather(
        _close(client, token, qid),
        client.post(f"/api/v1/answers/{aid}/accept", headers=_auth(token)),
    )
    assert sorted([close_resp.status_code, accept_resp.status_code]) == [204, 409]

    if accept_resp.status_code == 204:
        # 采纳赢：关闭必须失败（不变式 5），复关仍 409
        assert (await _close(client, token, qid)).status_code == 409
    else:
        # 关闭赢：采纳必须失败，复采仍 409
        retry = await client.post(f"/api/v1/answers/{aid}/accept", headers=_auth(token))
        assert retry.status_code == 409


# ---------------- Hardening：关贴 × 回答/投票/评论并发线性化 ----------------


async def _gather_with_close(
    idx: int,
    write_coro: Any,
    close_coro: Any,
    *,
    close_delay_s: float = 0.0,
) -> tuple[httpx.Response, httpx.Response]:
    """交替启动顺序并在需要时错峰，确保压出“写先赢”与“关先赢”两种真实线性化调度。"""

    async def _delayed_close() -> httpx.Response:
        if close_delay_s > 0:
            await asyncio.sleep(close_delay_s)
        return await close_coro

    if idx % 2 == 0:
        write_resp, close_resp = await asyncio.gather(write_coro, _delayed_close())
    else:
        close_resp, write_resp = await asyncio.gather(_delayed_close(), write_coro)
    return write_resp, close_resp


async def _count_rows(model: Any, column: Any, target_id: uuid.UUID) -> int:
    async with session_factory() as session:
        stmt = select(func.count()).select_from(model).where(column == target_id)
        return int((await session.execute(stmt)).scalar_one())


async def test_concurrent_post_answer_and_close_question_linearization(
    client: httpx.AsyncClient,
) -> None:
    """新增回答 × 关贴并发：覆盖两种线性化顺序，绝不出现“问题已关闭却多出回答”的撕裂态。"""
    asker_token, _ = await _register_and_login(client)
    answerer_token, _ = await _register_and_login(client)
    seen_write_won = False
    seen_close_won = False

    for idx in range(24):
        qid = await _ask(client, asker_token)
        post_resp, close_resp = await _gather_with_close(
            idx,
            client.post(
                f"/api/v1/questions/{qid}/answers",
                json={"body": f"并发回答-{idx}"},
                headers=_auth(answerer_token),
            ),
            _close(client, asker_token, qid),
        )
        assert close_resp.status_code == 204
        assert post_resp.status_code in (201, 409)

        detail = (await client.get(f"/api/v1/questions/{qid}")).json()
        assert detail["status"] == "closed"
        answer_count = await _count_rows(AnswerModel, AnswerModel.question_id, uuid.UUID(qid))
        if post_resp.status_code == 201:
            seen_write_won = True
            assert answer_count == 1
            assert len(detail["answers"]) == 1
        else:
            seen_close_won = True
            assert answer_count == 0
            assert detail["answers"] == []

        if seen_write_won and seen_close_won:
            break

    assert seen_write_won and seen_close_won


@pytest.mark.parametrize("target_kind", ["question", "answer"])
async def test_concurrent_vote_and_close_question_linearization(
    client: httpx.AsyncClient,
    target_kind: str,
) -> None:
    """投票 × 关贴并发（题票/答票）：409 时无投票落库且不触发声誉事件；204 时记票且关贴仍 204。"""
    asker_token, asker_id = await _register_and_login(client)
    answerer_token, answerer_id = await _register_and_login(client)
    voter_token, _ = await _register_and_login(client)
    target_author_id = uuid.UUID(asker_id if target_kind == "question" else answerer_id)
    expected_ledger_count = 0
    seen_write_won = False
    seen_close_won = False

    for idx in range(24):
        qid = await _ask(client, asker_token)
        if target_kind == "question":
            target_id = uuid.UUID(qid)
            vote_url = f"/api/v1/questions/{qid}/vote"
        else:
            aid = await _answer(client, answerer_token, qid)
            target_id = uuid.UUID(aid)
            vote_url = f"/api/v1/questions/{qid}/answers/{aid}/vote"

        delay = 0.005 * (idx // 2) if (idx % 2 == 0 and not seen_write_won and idx >= 2) else 0.0
        vote_resp, close_resp = await _gather_with_close(
            idx,
            client.post(vote_url, json={"direction": "up"}, headers=_auth(voter_token)),
            _close(client, asker_token, qid),
            close_delay_s=delay,
        )
        assert close_resp.status_code == 204
        assert vote_resp.status_code in (204, 409)

        detail = (await client.get(f"/api/v1/questions/{qid}")).json()
        assert detail["status"] == "closed"
        vote_count = await _count_rows(VoteModel, VoteModel.target_id, target_id)
        if vote_resp.status_code == 204:
            seen_write_won = True
            expected_ledger_count += 1
            assert vote_count == 1
            if target_kind == "answer":
                assert detail["answers"][0]["votes"] == 1
        else:
            seen_close_won = True
            assert vote_count == 0
            if target_kind == "answer":
                assert detail["answers"][0]["votes"] == 0

        ledger_count = await _count_rows(
            ReputationLedgerModel, ReputationLedgerModel.user_id, target_author_id
        )
        assert ledger_count == expected_ledger_count

        if seen_write_won and seen_close_won:
            break

    assert seen_write_won and seen_close_won


@pytest.mark.parametrize("target_kind", ["question", "answer"])
async def test_concurrent_comment_and_close_question_linearization(
    client: httpx.AsyncClient,
    target_kind: str,
) -> None:
    """评论 × 关贴并发（题评/答评）：409 时库内无新评论；201 时评论落库且关贴仍 204。"""
    asker_token, _ = await _register_and_login(client)
    commenter_token, _ = await _register_and_login(client)
    seen_write_won = False
    seen_close_won = False

    for idx in range(24):
        qid = await _ask(client, asker_token)
        if target_kind == "question":
            target_id = uuid.UUID(qid)
            comment_url = f"/api/v1/questions/{qid}/comments"
        else:
            aid = await _answer(client, asker_token, qid)
            target_id = uuid.UUID(aid)
            comment_url = f"/api/v1/answers/{aid}/comments"

        delay = 0.005 * (idx // 2) if (idx % 2 == 0 and not seen_write_won and idx >= 2) else 0.0
        comment_resp, close_resp = await _gather_with_close(
            idx,
            client.post(
                comment_url,
                json={"body": f"并发评论-{idx}"},
                headers=_auth(commenter_token),
            ),
            _close(client, asker_token, qid),
            close_delay_s=delay,
        )
        assert close_resp.status_code == 204
        assert comment_resp.status_code in (201, 409)

        detail = (await client.get(f"/api/v1/questions/{qid}")).json()
        assert detail["status"] == "closed"
        comments = (
            detail["comments"]
            if target_kind == "question"
            else detail["answers"][0]["comments"]
        )
        comment_count = await _count_rows(CommentModel, CommentModel.target_id, target_id)
        if comment_resp.status_code == 201:
            seen_write_won = True
            assert comment_count == 1
            assert len(comments) == 1
        else:
            seen_close_won = True
            assert comment_count == 0
            assert comments == []

        if seen_write_won and seen_close_won:
            break

    assert seen_write_won and seen_close_won
