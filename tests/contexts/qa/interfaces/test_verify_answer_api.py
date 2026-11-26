"""F15 教师/助教/管理员认证回答接口集成与并发测试（真实 PG + Redis）。

测试数据遵循真实知识约束，题材取自教材与官方文档：
- PostgreSQL Concurrency Control & MVCC（https://www.postgresql.org/docs/current/mvcc.html）
- Operating Systems: Three Easy Pieces（https://pages.cs.wisc.edu/~remzi/OSTEP/）
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import event, func, select

from app.contexts.identity.infrastructure.repository import SqlAlchemyUserRepository
from app.contexts.reputation.infrastructure.celery_app import celery_app
from app.contexts.reputation.infrastructure.models import ReputationLedgerModel
from app.main import create_app
from app.shared.engine import engine, session_factory

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


def _is_summary_select(statement: str) -> bool:
    upper = statement.upper()
    return (
        upper.lstrip().startswith("SELECT")
        and "FROM USERS" in upper
        and "STUDENTS" not in upper
        and "TEACHERS" not in upper
    )


class _SummarySqlCounter:
    def __init__(self) -> None:
        self.statements: list[str] = []

    def _listener(
        self,
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        if _is_summary_select(statement):
            self.statements.append(statement)

    def __enter__(self) -> _SummarySqlCounter:
        event.listen(engine.sync_engine, "before_cursor_execute", self._listener)
        return self

    def __exit__(self, *args: object) -> None:
        event.remove(engine.sync_engine, "before_cursor_execute", self._listener)


async def _register_and_login(
    client: httpx.AsyncClient,
    *,
    role: str = "student",
    nickname: str | None = None,
) -> dict[str, str]:
    base_role = "teacher" if role in ("teacher", "admin") else "student"
    ident = (
        str(uuid.uuid4().int)[:10]
        if base_role == "student"
        else f"T{uuid.uuid4().int % 90_000_000 + 10_000_000}"
    )
    payload: dict[str, Any] = {
        "role": base_role,
        "email": f"f15-vrf-{uuid.uuid4().hex[:10]}@campus.edu.cn",
        "password": "Passw0rd8",
    }
    if base_role == "student":
        payload["student_id"] = ident
    else:
        payload["staff_id"] = ident
    reg = await client.post("/api/v1/auth/register", json=payload)
    assert reg.status_code == 201, reg.text
    uid = uuid.UUID(str(reg.json()["id"]))
    if role in ("ta", "admin"):
        async with session_factory() as session:
            await SqlAlchemyUserRepository(session).update_role(uid, role)
            await session.commit()

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
    return {"id": str(uid), "token": token}


async def _ask(client: httpx.AsyncClient, token: str) -> str:
    resp = await client.post(
        "/api/v1/questions",
        json={
            "title": (
                f"PostgreSQL B-Tree 高并发查询如何通过 B-link 指针避免死锁？"
                f"#{uuid.uuid4().hex[:6]}"
            ),
            "body": (
                "在多事务同时分裂叶子节点并执行范围扫描时，high key 与右向兄弟指针的作用是什么？"
            ),
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def _answer(client: httpx.AsyncClient, token: str, qid: str, body: str | None = None) -> str:
    resp = await client.post(
        f"/api/v1/questions/{qid}/answers",
        json={
            "body": body
            or (
                "Lehman-Yao B-link 树在节点右链引入高键与右指针，"
                "查找线程遇分裂时向右追赶即可定位正确页，无需同时持有父子两层锁。"
            )
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def test_verify_answer_full_matrix_notifications_zero_reputation_and_zero_n_plus_1(
    client: httpx.AsyncClient,
) -> None:
    student = await _register_and_login(client, role="student", nickname="答主同学")
    teacher = await _register_and_login(client, role="teacher", nickname="李教授")
    ta = await _register_and_login(client, role="ta")
    admin = await _register_and_login(client, role="admin")

    qid = await _ask(client, student["token"])
    aid = await _answer(client, student["token"], qid)
    teacher_aid = await _answer(
        client,
        teacher["token"],
        qid,
        body="同题下教师自己的补充解答：B-link 结构在 PostgreSQL nbtree 实现中长期沿用。",
    )

    # 投票与评论（验证 verify 返回真实 votes 与有序 comments）
    assert (
        await client.post(
            f"/api/v1/questions/{qid}/answers/{aid}/vote",
            json={"direction": "up"},
            headers=_auth(ta["token"]),
        )
    ).status_code == 204
    comment = await client.post(
        f"/api/v1/answers/{aid}/comments",
        json={"body": "请确认高键比较是否包含等号边界？"},
        headers=_auth(student["token"]),
    )
    assert comment.status_code == 201

    # 1. 未认证 401 / 学生 403
    assert (await client.post(f"/api/v1/answers/{aid}/verify")).status_code == 401
    assert (await client.delete(f"/api/v1/answers/{aid}/verify")).status_code == 401
    assert (
        await client.post(f"/api/v1/answers/{aid}/verify", headers=_auth(student["token"]))
    ).status_code == 403
    assert (
        await client.delete(
            f"/api/v1/answers/{aid}/verify", headers=_auth(student["token"])
        )
    ).status_code == 403

    # 2. 记录认证前声誉流水数，确保认证与取消认证零声誉变动
    async with session_factory() as session:
        rep_before = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(ReputationLedgerModel)
                    .where(ReputationLedgerModel.user_id == uuid.UUID(student["id"]))
                )
            ).scalar_one()
        )

    # 3. 教师首次认证 → 200 + 完整 AnswerResponse，且向答主写 1 条 answer_verified 通知
    v1 = await client.post(
        f"/api/v1/answers/{aid}/verify", headers=_auth(teacher["token"])
    )
    assert v1.status_code == 200, v1.text
    d1 = v1.json()
    assert set(d1.keys()) == {
        "id",
        "body",
        "author_id",
        "author_name",
        "created_at",
        "votes",
        "is_accepted",
        "is_teacher_verified",
        "verified_by_name",
        "verified_at",
        "comments",
    }
    assert d1["is_teacher_verified"] is True
    assert d1["verified_by_name"] == "李教授"
    assert d1["verified_at"] is not None
    assert d1["votes"] == 1
    assert d1["author_name"] == "答主同学"
    assert len(d1["comments"]) == 1

    # 4. 助教重复认证 → 幂等 200，保持原 verified_by_name 与 verified_at，且不发第 2 条通知
    v2 = await client.post(f"/api/v1/answers/{aid}/verify", headers=_auth(ta["token"]))
    assert v2.status_code == 200, v2.text
    assert v2.json()["verified_by_name"] == "李教授"
    assert v2.json()["verified_at"] == d1["verified_at"]

    # 5. 详情页零 N+1（单次摘要 SQL）且编辑回答也回填 verified_by_name
    with _SummarySqlCounter() as counter:
        detail_resp = await client.get(f"/api/v1/questions/{qid}")
    assert detail_resp.status_code == 200
    assert len(counter.statements) == 1
    detail_ans = next(a for a in detail_resp.json()["answers"] if a["id"] == aid)
    assert detail_ans["is_teacher_verified"] is True
    assert detail_ans["verified_by_name"] == "李教授"
    assert detail_ans["verified_at"] == d1["verified_at"]

    edited = await client.patch(
        f"/api/v1/answers/{aid}",
        json={"body": "补充：nbtree 查找向右移动以 high key 为界，保证并发分裂下不漏项。"},
        headers=_auth(student["token"]),
    )
    assert edited.status_code == 200
    assert edited.json()["is_teacher_verified"] is True
    assert edited.json()["verified_by_name"] == "李教授"

    # 6. 自认证跳过通知；答主只收到 1 条 answer_verified 通知
    self_v = await client.post(
        f"/api/v1/answers/{teacher_aid}/verify", headers=_auth(teacher["token"])
    )
    assert self_v.status_code == 200
    teacher_notifs = (
        await client.get("/api/v1/notifications", headers=_auth(teacher["token"]))
    ).json()["items"]
    assert all(n["type"] != "answer_verified" for n in teacher_notifs)

    stu_notifs = (
        await client.get("/api/v1/notifications", headers=_auth(student["token"]))
    ).json()["items"]
    verified_notifs = [n for n in stu_notifs if n["type"] == "answer_verified"]
    assert len(verified_notifs) == 1
    assert verified_notifs[0]["target_type"] == "answer"
    assert verified_notifs[0]["target_id"] == aid
    assert verified_notifs[0]["question_id"] == qid
    assert verified_notifs[0]["actor_name"] == "李教授"

    # 7. 管理员取消认证（204）+ 幂等二次取消（204），无新通知、无声誉变动
    assert (
        await client.delete(
            f"/api/v1/answers/{aid}/verify", headers=_auth(admin["token"])
        )
    ).status_code == 204
    assert (
        await client.delete(
            f"/api/v1/answers/{aid}/verify", headers=_auth(admin["token"])
        )
    ).status_code == 204

    detail_after_unverify = (await client.get(f"/api/v1/questions/{qid}")).json()
    ans_after = next(a for a in detail_after_unverify["answers"] if a["id"] == aid)
    assert ans_after["is_teacher_verified"] is False
    assert ans_after["verified_by_name"] is None
    assert ans_after["verified_at"] is None

    async with session_factory() as session:
        rep_after = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(ReputationLedgerModel)
                    .where(ReputationLedgerModel.user_id == uuid.UUID(student["id"]))
                )
            ).scalar_one()
        )
    assert rep_after == rep_before

    # 8. 助教重新认证并展示默认兜底展示名“助教#<8位hex>”
    v_ta = await client.post(
        f"/api/v1/answers/{aid}/verify", headers=_auth(ta["token"])
    )
    assert v_ta.status_code == 200
    assert v_ta.json()["verified_by_name"] == f"助教#{uuid.UUID(ta['id']).hex[:8]}"

    # 9. 关闭问题后认证与取消认证均返回 409；软删后返回 404
    assert (
        await client.post(f"/api/v1/questions/{qid}/close", headers=_auth(student["token"]))
    ).status_code == 204
    assert (
        await client.post(f"/api/v1/answers/{aid}/verify", headers=_auth(admin["token"]))
    ).status_code == 409
    assert (
        await client.delete(f"/api/v1/answers/{aid}/verify", headers=_auth(admin["token"]))
    ).status_code == 409

    assert (
        await client.delete(f"/api/v1/answers/{aid}", headers=_auth(student["token"]))
    ).status_code == 204
    assert (
        await client.post(f"/api/v1/answers/{aid}/verify", headers=_auth(admin["token"]))
    ).status_code == 404
    assert (
        await client.delete(f"/api/v1/answers/{aid}/verify", headers=_auth(admin["token"]))
    ).status_code == 404


async def test_concurrent_verify_close_delete_and_duplicate_notifications(
    client: httpx.AsyncClient,
) -> None:
    """并发实证（asyncio.gather）：认证×关贴、认证×删答、多教师并发重复认证仅发 1 条通知。"""
    student = await _register_and_login(client, role="student")
    teachers = [await _register_and_login(client, role="teacher") for _ in range(5)]

    # 1. 认证 × 关贴（6 轮线性化验证）
    for _ in range(6):
        qid = await _ask(client, student["token"])
        aid = await _answer(client, student["token"], qid)
        v_resp, c_resp = await asyncio.gather(
            client.post(f"/api/v1/answers/{aid}/verify", headers=_auth(teachers[0]["token"])),
            client.post(f"/api/v1/questions/{qid}/close", headers=_auth(student["token"])),
        )
        assert c_resp.status_code == 204
        assert v_resp.status_code in (200, 409)
        detail = (await client.get(f"/api/v1/questions/{qid}")).json()
        assert detail["status"] == "closed"
        assert detail["answers"][0]["is_teacher_verified"] is (v_resp.status_code == 200)

    # 2. 认证 × 软删回答（6 轮线性化验证）
    for _ in range(6):
        qid = await _ask(client, student["token"])
        aid = await _answer(client, student["token"], qid)
        v_resp, d_resp = await asyncio.gather(
            client.post(f"/api/v1/answers/{aid}/verify", headers=_auth(teachers[0]["token"])),
            client.delete(f"/api/v1/answers/{aid}", headers=_auth(student["token"])),
        )
        assert d_resp.status_code == 204
        assert v_resp.status_code in (200, 404)
        detail = (await client.get(f"/api/v1/questions/{qid}")).json()
        assert detail["answers"] == []

    # 3. 5 名教师并发认证同一回答：全部返回相同首次认证状态且答主只收到 1 条通知
    qid_dup = await _ask(client, student["token"])
    aid_dup = await _answer(client, student["token"], qid_dup)
    resps = await asyncio.gather(
        *(
            client.post(f"/api/v1/answers/{aid_dup}/verify", headers=_auth(t["token"]))
            for t in teachers
        )
    )
    assert all(r.status_code == 200 for r in resps)
    verifiers = {r.json()["verified_by_name"] for r in resps}
    verified_ats = {r.json()["verified_at"] for r in resps}
    assert len(verifiers) == 1
    assert len(verified_ats) == 1

    notifs = (
        await client.get(
            "/api/v1/notifications", params={"page_size": 50}, headers=_auth(student["token"])
        )
    ).json()["items"]
    matching = [
        n for n in notifs if n["type"] == "answer_verified" and n["target_id"] == aid_dup
    ]
    assert len(matching) == 1
