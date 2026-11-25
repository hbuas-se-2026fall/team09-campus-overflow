"""F18 内容举报与管理员后台全链路及并发集成测试（真实 PG + Redis）。"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, func, select

from app.contexts.identity.infrastructure.models import UserModel
from app.contexts.identity.infrastructure.repository import SqlAlchemyUserRepository
from app.contexts.qa.infrastructure.models import QuestionModel, ReportModel
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
        "email": f"f18-{uuid.uuid4().hex[:10]}@campus.edu.cn",
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
    return {"id": str(reg.json()["id"]), "token": token}


async def _promote_role(user_id: str, new_role: str) -> None:
    async with session_factory() as session:
        await SqlAlchemyUserRepository(session).update_role(
            uuid.UUID(user_id),
            new_role,  # type: ignore[arg-type]
        )
        await session.commit()


async def _cleanup(
    report_ids: list[uuid.UUID],
    question_ids: list[uuid.UUID],
    user_ids: list[uuid.UUID],
) -> None:
    async with session_factory() as session:
        if report_ids:
            await session.execute(
                delete(ReportModel).where(ReportModel.id.in_(report_ids))
            )
        if question_ids:
            await session.execute(
                delete(QuestionModel).where(QuestionModel.id.in_(question_ids))
            )
        if user_ids:
            await session.execute(
                delete(UserModel).where(UserModel.id.in_(user_ids))
            )
        await session.commit()


async def test_reports_rbac_and_full_3x2_resolution_matrix(
    client: httpx.AsyncClient,
) -> None:
    suffix = uuid.uuid4().hex[:6].upper()
    admin = await _register_and_login(client, role="teacher", nickname="主管理员")
    await _promote_role(admin["id"], "admin")
    teacher = await _register_and_login(client, role="teacher", nickname="悬赏教师")
    ta = await _register_and_login(client, role="student", nickname="举报助教")
    await _promote_role(ta["id"], "ta")
    student1 = await _register_and_login(client, role="student", nickname="提问学生")
    student2 = await _register_and_login(client, role="student", nickname="举报学生")

    user_ids = [
        uuid.UUID(u["id"]) for u in (admin, teacher, ta, student1, student2)
    ]
    question_ids: list[uuid.UUID] = []
    report_ids: list[uuid.UUID] = []

    try:
        # 1. RBAC：未登录 401，非 admin 访问后台 403
        assert (
            await client.post(
                "/api/v1/reports",
                json={
                    "target_type": "question",
                    "target_id": str(uuid.uuid4()),
                    "reason": "未认证举报尝试",
                },
            )
        ).status_code == 401
        assert (await client.get("/api/v1/admin/reports")).status_code == 401
        for non_admin in (student1, teacher, ta):
            assert (
                await client.get(
                    "/api/v1/admin/reports", headers=_auth(non_admin["token"])
                )
            ).status_code == 403
            assert (
                await client.post(
                    f"/api/v1/admin/reports/{uuid.uuid4()}/resolve",
                    json={"action": "dismiss"},
                    headers=_auth(non_admin["token"]),
                )
            ).status_code == 403

        # 2. 构造两题：q_bounty（教师发 25 分悬赏）与 q_accepted（含已采纳与未采纳各一答）
        q_bounty_resp = await client.post(
            "/api/v1/questions",
            json={
                "title": f"计算机组成原理 Cache 一致性协议 {suffix}",
                "body": "MESI 状态机转换与总线嗅探问题。",
            },
            headers=_auth(student1["token"]),
        )
        assert q_bounty_resp.status_code == 201
        q_bounty_id = q_bounty_resp.json()["id"]
        question_ids.append(uuid.UUID(q_bounty_id))
        assert (
            await client.post(
                f"/api/v1/questions/{q_bounty_id}/bounty",
                json={"amount": 25},
                headers=_auth(teacher["token"]),
            )
        ).status_code == 201

        q_acc_resp = await client.post(
            "/api/v1/questions",
            json={
                "title": f"编译原理 LR(1) 分析表冲突消解 {suffix}",
                "body": "移进-归约冲突与归约-归约冲突处理。",
            },
            headers=_auth(student1["token"]),
        )
        assert q_acc_resp.status_code == 201
        q_acc_id = q_acc_resp.json()["id"]
        question_ids.append(uuid.UUID(q_acc_id))

        ans_acc_resp = await client.post(
            f"/api/v1/questions/{q_acc_id}/answers",
            json={"body": "通过优先级与结合性声明消解算符文法移进-归约冲突。"},
            headers=_auth(teacher["token"]),
        )
        assert ans_acc_resp.status_code == 201
        ans_acc_id = ans_acc_resp.json()["id"]

        ans_unacc_resp = await client.post(
            f"/api/v1/questions/{q_acc_id}/answers",
            json={"body": "无关水贴刷屏内容示例。"},
            headers=_auth(student2["token"]),
        )
        assert ans_unacc_resp.status_code == 201
        ans_unacc_id = ans_unacc_resp.json()["id"]

        assert (
            await client.post(
                f"/api/v1/answers/{ans_acc_id}/accept",
                headers=_auth(student1["token"]),
            )
        ).status_code == 204

        # 3. 举报：student / teacher / ta 均 201，重复 pending 409 不泄露 exc.orig
        rep1 = await client.post(
            "/api/v1/reports",
            json={
                "target_type": "question",
                "target_id": q_bounty_id,
                "reason": "该问题存在引战与灌水风险",
            },
            headers=_auth(student2["token"]),
        )
        assert rep1.status_code == 201
        rep1_id = rep1.json()["id"]
        report_ids.append(uuid.UUID(rep1_id))

        dup_rep = await client.post(
            "/api/v1/reports",
            json={
                "target_type": "question",
                "target_id": q_bounty_id,
                "reason": "重复提交举报尝试",
            },
            headers=_auth(student2["token"]),
        )
        assert dup_rep.status_code == 409
        assert "uq_reports" not in dup_rep.text

        # ta 举报同一题作第二单
        rep2 = await client.post(
            "/api/v1/reports",
            json={
                "target_type": "question",
                "target_id": q_bounty_id,
                "reason": "助教同步提交关贴后清理工单",
            },
            headers=_auth(ta["token"]),
        )
        assert rep2.status_code == 201
        rep2_id = rep2.json()["id"]
        report_ids.append(uuid.UUID(rep2_id))

        # teacher 举报含采纳答案的问题；student2 举报已采纳与未采纳回答
        rep_acc_q = await client.post(
            "/api/v1/reports",
            json={
                "target_type": "question",
                "target_id": q_acc_id,
                "reason": "已采纳问题保护矩阵测试",
            },
            headers=_auth(teacher["token"]),
        )
        assert rep_acc_q.status_code == 201
        rep_acc_q_id = rep_acc_q.json()["id"]
        report_ids.append(uuid.UUID(rep_acc_q_id))

        rep_acc_a = await client.post(
            "/api/v1/reports",
            json={
                "target_type": "answer",
                "target_id": ans_acc_id,
                "reason": "已采纳回答保护矩阵测试",
            },
            headers=_auth(student2["token"]),
        )
        assert rep_acc_a.status_code == 201
        rep_acc_a_id = rep_acc_a.json()["id"]
        report_ids.append(uuid.UUID(rep_acc_a_id))

        rep_unacc_a = await client.post(
            "/api/v1/reports",
            json={
                "target_type": "answer",
                "target_id": ans_unacc_id,
                "reason": "未采纳回答广告刷屏清理",
            },
            headers=_auth(student1["token"]),
        )
        assert rep_unacc_a.status_code == 201
        rep_unacc_a_id = rep_unacc_a.json()["id"]
        report_ids.append(uuid.UUID(rep_unacc_a_id))

        # 4. 3×2 矩阵执行
        # (a) close_question 关闭 q_bounty 并退还 25 分悬赏
        res_close = await client.post(
            f"/api/v1/admin/reports/{rep1_id}/resolve",
            json={"action": "close_question", "note": "管理员关闭讨论并退悬赏"},
            headers=_auth(admin["token"]),
        )
        assert res_close.status_code == 200
        assert res_close.json()["status"] == "resolved"
        assert res_close.json()["resolved_by_name"] == "主管理员"
        pts = await client.get(
            "/api/v1/users/me/points", headers=_auth(teacher["token"])
        )
        assert pts.json()["balance"] == 100  # 100 - 25 + 25

        # (b) 已关贴再 close_question → 409（保持 pending），再 soft_delete → 200，全链路不可见
        assert (
            await client.post(
                f"/api/v1/admin/reports/{rep2_id}/resolve",
                json={"action": "close_question"},
                headers=_auth(admin["token"]),
            )
        ).status_code == 409
        res_del_q = await client.post(
            f"/api/v1/admin/reports/{rep2_id}/resolve",
            json={"action": "soft_delete", "note": "管理员软删除违规问题"},
            headers=_auth(admin["token"]),
        )
        assert res_del_q.status_code == 200
        assert (await client.get(f"/api/v1/questions/{q_bounty_id}")).status_code == 404
        search_deleted = await client.get("/api/v1/questions", params={"q": suffix})
        assert q_bounty_id not in {i["id"] for i in search_deleted.json()["items"]}

        # 对已删问题再提交举报 → 404
        assert (
            await client.post(
                "/api/v1/reports",
                json={
                    "target_type": "question",
                    "target_id": q_bounty_id,
                    "reason": "已删目标不可被举报",
                },
                headers=_auth(student1["token"]),
            )
        ).status_code == 404

        # (c) 含采纳答案的问题：禁 close_question 409、禁 soft_delete 409、允许 dismiss 200
        for forbidden_action in ("close_question", "soft_delete"):
            assert (
                await client.post(
                    f"/api/v1/admin/reports/{rep_acc_q_id}/resolve",
                    json={"action": forbidden_action},
                    headers=_auth(admin["token"]),
                )
            ).status_code == 409
        assert (
            await client.post(
                f"/api/v1/admin/reports/{rep_acc_q_id}/resolve",
                json={"action": "dismiss"},
                headers=_auth(admin["token"]),
            )
        ).status_code == 200

        # (d) 回答：close_question → 422；已采纳回答 soft_delete → 409；未采纳回答 soft_delete → 200
        assert (
            await client.post(
                f"/api/v1/admin/reports/{rep_acc_a_id}/resolve",
                json={"action": "close_question"},
                headers=_auth(admin["token"]),
            )
        ).status_code == 422
        assert (
            await client.post(
                f"/api/v1/admin/reports/{rep_acc_a_id}/resolve",
                json={"action": "soft_delete"},
                headers=_auth(admin["token"]),
            )
        ).status_code == 409
        assert (
            await client.post(
                f"/api/v1/admin/reports/{rep_acc_a_id}/resolve",
                json={"action": "dismiss"},
                headers=_auth(admin["token"]),
            )
        ).status_code == 200

        # dismiss 后允许再次举报同一目标
        refile = await client.post(
            "/api/v1/reports",
            json={
                "target_type": "answer",
                "target_id": ans_acc_id,
                "reason": "驳回后再次举报同一回答",
            },
            headers=_auth(student2["token"]),
        )
        assert refile.status_code == 201
        report_ids.append(uuid.UUID(refile.json()["id"]))

        # 未采纳回答软删后在详情中不可见
        assert (
            await client.post(
                f"/api/v1/admin/reports/{rep_unacc_a_id}/resolve",
                json={"action": "soft_delete"},
                headers=_auth(admin["token"]),
            )
        ).status_code == 200
        detail_after = await client.get(f"/api/v1/questions/{q_acc_id}")
        assert [a["id"] for a in detail_after.json()["answers"]] == [ans_acc_id]
    finally:
        await _cleanup(report_ids, question_ids, user_ids)


async def test_reports_duplicate_and_admin_resolve_concurrency(
    client: httpx.AsyncClient,
) -> None:
    suffix = uuid.uuid4().hex[:6].upper()
    admin1 = await _register_and_login(client, role="teacher", nickname="并发管理员甲")
    await _promote_role(admin1["id"], "admin")
    admin2 = await _register_and_login(client, role="teacher", nickname="并发管理员乙")
    await _promote_role(admin2["id"], "admin")
    teacher = await _register_and_login(client, role="teacher", nickname="并发悬赏教师")
    student = await _register_and_login(client, role="student", nickname="并发举报学生")

    user_ids = [uuid.UUID(u["id"]) for u in (admin1, admin2, teacher, student)]
    question_ids: list[uuid.UUID] = []
    report_ids: list[uuid.UUID] = []

    try:
        q_resp = await client.post(
            "/api/v1/questions",
            json={
                "title": f"分布式共识 Raft 领导者选举超时 {suffix}",
                "body": "并发举报与并发处置悬赏退款实证测试。",
            },
            headers=_auth(student["token"]),
        )
        assert q_resp.status_code == 201
        qid = q_resp.json()["id"]
        question_ids.append(uuid.UUID(qid))

        assert (
            await client.post(
                f"/api/v1/questions/{qid}/bounty",
                json={"amount": 40},
                headers=_auth(teacher["token"]),
            )
        ).status_code == 201

        # 1. 6 并发重复提交待处理举报：仅 1 个 201，其余 5 个 409
        dup_tasks = [
            client.post(
                "/api/v1/reports",
                json={
                    "target_type": "question",
                    "target_id": qid,
                    "reason": f"并发举报测试理由第 {idx} 路",
                },
                headers=_auth(student["token"]),
            )
            for idx in range(6)
        ]
        dup_resps = await asyncio.gather(*dup_tasks)
        dup_codes = [r.status_code for r in dup_resps]
        assert dup_codes.count(201) == 1, dup_codes
        assert dup_codes.count(409) == 5, dup_codes
        winner_report = next(r for r in dup_resps if r.status_code == 201)
        rid = winner_report.json()["id"]
        report_ids.append(uuid.UUID(rid))

        async with session_factory() as session:
            db_pending = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(ReportModel)
                        .where(
                            ReportModel.target_id == uuid.UUID(qid),
                            ReportModel.status == "pending",
                        )
                    )
                ).scalar_one()
            )
            assert db_pending == 1

        # 2. 6 并发多管理员抢审同一举报（soft_delete）：仅 1 个 200，其余 5 个 409，悬赏恰好退 1 次
        resolve_tasks = [
            client.post(
                f"/api/v1/admin/reports/{rid}/resolve",
                json={"action": "soft_delete", "note": f"管理员抢审 #{idx}"},
                headers=_auth((admin1 if idx % 2 == 0 else admin2)["token"]),
            )
            for idx in range(6)
        ]
        resolve_resps = await asyncio.gather(*resolve_tasks)
        resolve_codes = [r.status_code for r in resolve_resps]
        assert resolve_codes.count(200) == 1, resolve_codes
        assert resolve_codes.count(409) == 5, resolve_codes

        pts = await client.get(
            "/api/v1/users/me/points", headers=_auth(teacher["token"])
        )
        assert pts.json()["balance"] == 100
        assert sum(
            1 for entry in pts.json()["entries"] if entry["source"] == "bounty_refund"
        ) == 1
    finally:
        await _cleanup(report_ids, question_ids, user_ids)


async def test_admin_reports_list_filters_and_display_name_backfill(
    client: httpx.AsyncClient,
) -> None:
    """真库验证默认 pending、status=all、组合筛选与展示名批量回填。"""
    suffix = uuid.uuid4().hex[:6].upper()
    admin = await _register_and_login(client, role="teacher", nickname="列表审核员")
    await _promote_role(admin["id"], "admin")
    teacher = await _register_and_login(client, role="teacher", nickname="提问教师")
    student_no_nick = await _register_and_login(client, role="student", nickname=None)
    student_with_nick = await _register_and_login(client, role="student", nickname="举报同学乙")

    user_ids = [
        uuid.UUID(u["id"])
        for u in (admin, teacher, student_no_nick, student_with_nick)
    ]
    question_ids: list[uuid.UUID] = []
    report_ids: list[uuid.UUID] = []

    try:
        q_resp = await client.post(
            "/api/v1/questions",
            json={
                "title": f"计算机网络 TCP 拥塞控制阶段切换 {suffix}",
                "body": "比较慢开始、拥塞避免与快恢复窗口变化。",
            },
            headers=_auth(teacher["token"]),
        )
        assert q_resp.status_code == 201
        qid = q_resp.json()["id"]
        question_ids.append(uuid.UUID(qid))

        ans_resp = await client.post(
            f"/api/v1/questions/{qid}/answers",
            json={"body": "无关测试水贴回答内容。"},
            headers=_auth(student_with_nick["token"]),
        )
        assert ans_resp.status_code == 201
        aid = ans_resp.json()["id"]

        r_dismiss = await client.post(
            "/api/v1/reports",
            json={
                "target_type": "question",
                "target_id": qid,
                "reason": "筛选测试驳回工单",
            },
            headers=_auth(student_no_nick["token"]),
        )
        assert r_dismiss.status_code == 201
        rid_dismiss = r_dismiss.json()["id"]
        report_ids.append(uuid.UUID(rid_dismiss))

        r_resolve = await client.post(
            "/api/v1/reports",
            json={
                "target_type": "answer",
                "target_id": aid,
                "reason": "筛选测试软删回答工单",
            },
            headers=_auth(teacher["token"]),
        )
        assert r_resolve.status_code == 201
        rid_resolve = r_resolve.json()["id"]
        report_ids.append(uuid.UUID(rid_resolve))

        r_pending = await client.post(
            "/api/v1/reports",
            json={
                "target_type": "question",
                "target_id": qid,
                "reason": "筛选测试待审核工单",
            },
            headers=_auth(student_with_nick["token"]),
        )
        assert r_pending.status_code == 201
        rid_pending = r_pending.json()["id"]
        report_ids.append(uuid.UUID(rid_pending))

        # 处置 R1 -> dismissed，R2 -> resolved；R3 维持 pending
        assert (
            await client.post(
                f"/api/v1/admin/reports/{rid_dismiss}/resolve",
                json={"action": "dismiss", "note": "正常学术问题"},
                headers=_auth(admin["token"]),
            )
        ).status_code == 200
        assert (
            await client.post(
                f"/api/v1/admin/reports/{rid_resolve}/resolve",
                json={"action": "soft_delete", "note": "清理无关水贴"},
                headers=_auth(admin["token"]),
            )
        ).status_code == 200

        # 1. 默认（无 status 参数）仅返回 pending（不含 R1/R2）
        res_default = await client.get(
            "/api/v1/admin/reports",
            params={"page_size": 100},
            headers=_auth(admin["token"]),
        )
        assert res_default.status_code == 200
        default_items = {
            item["id"]: item
            for item in res_default.json()["items"]
            if item["id"] in {rid_dismiss, rid_resolve, rid_pending}
        }
        assert set(default_items.keys()) == {rid_pending}
        assert default_items[rid_pending]["reporter_name"] == "举报同学乙"
        assert default_items[rid_pending]["resolved_by_name"] is None

        # 2. status=all 返回全部三态并回填展示名（含无昵称回退 学生#<hex>）
        res_all = await client.get(
            "/api/v1/admin/reports",
            params={"status": "all", "page_size": 100},
            headers=_auth(admin["token"]),
        )
        assert res_all.status_code == 200
        all_items = {
            item["id"]: item
            for item in res_all.json()["items"]
            if item["id"] in {rid_dismiss, rid_resolve, rid_pending}
        }
        assert set(all_items.keys()) == {rid_dismiss, rid_resolve, rid_pending}
        assert all_items[rid_dismiss]["reporter_name"].startswith("学生#")
        assert all_items[rid_dismiss]["resolved_by_name"] == "列表审核员"
        assert all_items[rid_resolve]["reporter_name"] == "提问教师"
        assert all_items[rid_resolve]["resolved_by_name"] == "列表审核员"

        # 3. 组合筛选 status=resolved + target_type；status=dismissed；非法 422
        res_ans = await client.get(
            "/api/v1/admin/reports",
            params={"status": "resolved", "target_type": "answer", "page_size": 100},
            headers=_auth(admin["token"]),
        )
        assert res_ans.status_code == 200
        ans_ids = {item["id"] for item in res_ans.json()["items"]}
        assert rid_resolve in ans_ids
        assert rid_dismiss not in ans_ids
        assert rid_pending not in ans_ids

        res_q_resolved = await client.get(
            "/api/v1/admin/reports",
            params={"status": "resolved", "target_type": "question", "page_size": 100},
            headers=_auth(admin["token"]),
        )
        assert res_q_resolved.status_code == 200
        assert rid_resolve not in {item["id"] for item in res_q_resolved.json()["items"]}

        res_dis = await client.get(
            "/api/v1/admin/reports",
            params={"status": "dismissed", "page_size": 100},
            headers=_auth(admin["token"]),
        )
        assert res_dis.status_code == 200
        assert rid_dismiss in {item["id"] for item in res_dis.json()["items"]}

        assert (
            await client.get(
                "/api/v1/admin/reports",
                params={"status": "invalid"},
                headers=_auth(admin["token"]),
            )
        ).status_code == 422
    finally:
        await _cleanup(report_ids, question_ids, user_ids)
