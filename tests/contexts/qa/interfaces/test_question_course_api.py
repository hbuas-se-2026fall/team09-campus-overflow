"""F17 问题关联课程、课程筛选与课程榜单 API 全链路及并发测试（真实 PG + Redis）。"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, event, func, select

from app.contexts.course.infrastructure.models import CourseModel
from app.contexts.identity.infrastructure.models import UserModel
from app.contexts.identity.infrastructure.repository import SqlAlchemyUserRepository
from app.contexts.qa.infrastructure.models import QuestionModel
from app.contexts.reputation.infrastructure.models import ReputationLedgerModel
from app.main import create_app
from app.shared.engine import engine, session_factory

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
        "email": f"f17-{uuid.uuid4().hex[:10]}@campus.edu.cn",
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
    course_ids: list[uuid.UUID],
    question_ids: list[uuid.UUID],
    user_ids: list[uuid.UUID],
) -> None:
    async with session_factory() as session:
        if question_ids:
            await session.execute(
                delete(QuestionModel).where(QuestionModel.id.in_(question_ids))
            )
        if course_ids:
            await session.execute(
                delete(CourseModel).where(CourseModel.id.in_(course_ids))
            )
        if user_ids:
            await session.execute(
                delete(UserModel).where(UserModel.id.in_(user_ids))
            )
        await session.commit()


async def test_question_course_access_filter_hydration_and_leaderboard_api(
    client: httpx.AsyncClient,
) -> None:
    suffix = uuid.uuid4().hex[:6].upper()
    teacher = await _register_and_login(client, role="teacher", nickname="课程教师")
    admin_u = await _register_and_login(client, role="teacher", nickname="教务管理")
    await _promote_role(admin_u["id"], "admin")
    ta_u = await _register_and_login(client, role="student", nickname="课程助教")
    await _promote_role(ta_u["id"], "ta")
    enrolled_stu = await _register_and_login(client, role="student", nickname="已选学生")
    other_stu = await _register_and_login(client, role="student", nickname="未选学生")

    user_ids = [
        uuid.UUID(u["id"])
        for u in (teacher, admin_u, ta_u, enrolled_stu, other_stu)
    ]
    course_ids: list[uuid.UUID] = []
    question_ids: list[uuid.UUID] = []

    try:
        # 1. 创建两门课程，仅让 enrolled_stu 选修课程 1
        c1_resp = await client.post(
            "/api/v1/courses",
            json={
                "code": f"CS-SE-{suffix}",
                "name": "软件工程",
                "semester": f"2026-Fall-{suffix}",
            },
            headers=_auth(teacher["token"]),
        )
        assert c1_resp.status_code == 201, c1_resp.text
        c1_id = c1_resp.json()["id"]
        course_ids.append(uuid.UUID(c1_id))

        c2_resp = await client.post(
            "/api/v1/courses",
            json={
                "code": f"CS-OS-{suffix}",
                "name": "操作系统",
                "semester": f"2026-Fall-{suffix}",
            },
            headers=_auth(admin_u["token"]),
        )
        assert c2_resp.status_code == 201, c2_resp.text
        c2_id = c2_resp.json()["id"]
        course_ids.append(uuid.UUID(c2_id))

        assert (
            await client.post(
                f"/api/v1/courses/{c1_id}/enroll",
                headers=_auth(enrolled_stu["token"]),
            )
        ).status_code == 201

        # 空课榜单 200 entries=[]; 不存在课程榜单 404
        empty_lb = await client.get(f"/api/v1/courses/{c1_id}/leaderboard")
        assert empty_lb.status_code == 200
        assert empty_lb.json()["entries"] == []
        assert empty_lb.json()["course_name"] == "软件工程"
        assert (
            await client.get(f"/api/v1/courses/{uuid.uuid4()}/leaderboard")
        ).status_code == 404

        # 2. 全角色发问准入矩阵
        assert (
            await client.post(
                "/api/v1/questions",
                json={
                    "title": "未选课学生提问尝试",
                    "body": "未选修课程时应返回 403。",
                    "course_id": c1_id,
                },
                headers=_auth(other_stu["token"]),
            )
        ).status_code == 403

        assert (
            await client.post(
                "/api/v1/questions",
                json={
                    "title": "缺失课程提问尝试",
                    "body": "课程不存在时应返回 404。",
                    "course_id": str(uuid.uuid4()),
                },
                headers=_auth(teacher["token"]),
            )
        ).status_code == 404

        # 已选学生发问 201
        q_stu_resp = await client.post(
            "/api/v1/questions",
            json={
                "title": f"领域层为何禁依赖框架 {suffix}",
                "body": "软件工程课程关于六边形架构的思考。",
                "tags": [f"se-{suffix}"],
                "course_id": c1_id,
            },
            headers=_auth(enrolled_stu["token"]),
        )
        assert q_stu_resp.status_code == 201, q_stu_resp.text
        q_stu_id = q_stu_resp.json()["id"]
        question_ids.append(uuid.UUID(q_stu_id))
        assert q_stu_resp.json()["course_id"] == c1_id
        assert q_stu_resp.json()["course_name"] == "软件工程"

        # 教师/助教/管理员跨课程发问 201
        for staff, title in (
            (teacher, f"教师跨课提问 {suffix}"),
            (ta_u, f"助教跨课提问 {suffix}"),
            (admin_u, f"管理员跨课提问 {suffix}"),
        ):
            r = await client.post(
                "/api/v1/questions",
                json={
                    "title": title,
                    "body": "教职人员允许跨课程发布课程讨论问题。",
                    "tags": [f"se-{suffix}"],
                    "course_id": c1_id,
                },
                headers=_auth(staff["token"]),
            )
            assert r.status_code == 201, r.text
            question_ids.append(uuid.UUID(r.json()["id"]))

        # 无课程提问向后兼容
        q_free = await client.post(
            "/api/v1/questions",
            json={"title": f"独立问题 {suffix}", "body": "不绑定课程。"},
            headers=_auth(other_stu["token"]),
        )
        assert q_free.status_code == 201
        q_free_id = q_free.json()["id"]
        question_ids.append(uuid.UUID(q_free_id))
        assert q_free.json()["course_id"] is None
        assert q_free.json()["course_name"] is None

        # 3. 编辑课程关联（保留 / 改绑失败 403 / 解绑 / 关闭态 409）
        keep_resp = await client.patch(
            f"/api/v1/questions/{q_stu_id}",
            json={"title": f"领域层为何禁依赖框架（已修订）{suffix}"},
            headers=_auth(enrolled_stu["token"]),
        )
        assert keep_resp.status_code == 200
        assert keep_resp.json()["course_id"] == c1_id

        assert (
            await client.patch(
                f"/api/v1/questions/{q_stu_id}",
                json={"course_id": c2_id},
                headers=_auth(enrolled_stu["token"]),
            )
        ).status_code == 403

        # 解绑并重绑 c1
        unbind = await client.patch(
            f"/api/v1/questions/{q_stu_id}",
            json={"course_id": None},
            headers=_auth(enrolled_stu["token"]),
        )
        assert unbind.status_code == 200
        assert unbind.json()["course_id"] is None
        rebind = await client.patch(
            f"/api/v1/questions/{q_stu_id}",
            json={"course_id": c1_id},
            headers=_auth(enrolled_stu["token"]),
        )
        assert rebind.status_code == 200
        assert rebind.json()["course_name"] == "软件工程"

        # 4. 列表按 course_id 筛选 + 与 tag/status/q 组合 + 零 N+1 courses SQL 计数 + 详情/相关问题
        courses_sql_count = 0

        def _count_courses_sql(
            _conn: object, _cur: object, statement: str, *_rest: object
        ) -> None:
            nonlocal courses_sql_count
            if "FROM courses" in statement:
                courses_sql_count += 1

        event.listen(engine.sync_engine, "before_cursor_execute", _count_courses_sql)
        try:
            courses_sql_count = 0
            list_resp = await client.get(
                "/api/v1/questions",
                params={
                    "course_id": c1_id,
                    "tag": f"se-{suffix}",
                    "status": "open",
                    "q": suffix,
                    "page_size": 20,
                },
            )
            assert list_resp.status_code == 200, list_resp.text
            list_json = list_resp.json()
            assert list_json["total"] == 4
            assert len(list_json["items"]) == 4
            assert all(item["course_name"] == "软件工程" for item in list_json["items"])
            # 批量一次 IN 查询回填 course_name（绝不 N+1）
            assert courses_sql_count == 1
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", _count_courses_sql)

        detail = await client.get(f"/api/v1/questions/{q_stu_id}")
        assert detail.status_code == 200
        assert detail.json()["course_id"] == c1_id
        assert detail.json()["course_name"] == "软件工程"

        related = await client.get(f"/api/v1/questions/{q_stu_id}/related")
        assert related.status_code == 200
        assert len(related.json()) == 3
        assert all(item["course_name"] == "软件工程" for item in related.json())

        # 5. 课程榜单：回答 + 多票 + 采纳 + 软删除排除 + 关闭态 409 编辑
        a_teacher = await client.post(
            f"/api/v1/questions/{q_stu_id}/answers",
            json={"body": "遵循依赖倒置原则，仅由外层适配器实现领域端口。"},
            headers=_auth(teacher["token"]),
        )
        assert a_teacher.status_code == 201
        a_teacher_id = a_teacher.json()["id"]

        a_ta = await client.post(
            f"/api/v1/questions/{q_stu_id}/answers",
            json={"body": "补充：tests/test_architecture.py 用 AST 静态检查守卫 A1-A8。"},
            headers=_auth(ta_u["token"]),
        )
        assert a_ta.status_code == 201
        a_ta_id = a_ta.json()["id"]

        # 给教师回答投 2 票（验证不乘倍膨胀 answer_count），采纳教师回答
        for voter in (enrolled_stu, other_stu):
            assert (
                await client.post(
                    f"/api/v1/questions/{q_stu_id}/answers/{a_teacher_id}/vote",
                    json={"direction": "up"},
                    headers=_auth(voter["token"]),
                )
            ).status_code == 204
        assert (
            await client.post(
                f"/api/v1/answers/{a_teacher_id}/accept",
                headers=_auth(enrolled_stu["token"]),
            )
        ).status_code == 204

        # 给助教回答投 1 票
        assert (
            await client.post(
                f"/api/v1/questions/{q_stu_id}/answers/{a_ta_id}/vote",
                json={"direction": "up"},
                headers=_auth(other_stu["token"]),
            )
        ).status_code == 204

        lb_resp = await client.get(f"/api/v1/courses/{c1_id}/leaderboard")
        assert lb_resp.status_code == 200, lb_resp.text
        entries = lb_resp.json()["entries"]
        assert len(entries) == 2
        assert entries[0]["user_id"] == teacher["id"]
        assert entries[0]["display_name"] == "课程教师"
        assert entries[0]["accepted_count"] == 1
        assert entries[0]["net_votes"] == 2
        assert entries[0]["answer_count"] == 1
        assert entries[0]["rank"] == 1
        assert entries[1]["user_id"] == ta_u["id"]
        assert entries[1]["rank"] == 2

        # 软删除未采纳助教回答后立即从课程榜单剔除
        assert (
            await client.delete(
                f"/api/v1/answers/{a_ta_id}", headers=_auth(ta_u["token"])
            )
        ).status_code == 204
        lb_after_del = await client.get(f"/api/v1/courses/{c1_id}/leaderboard")
        assert len(lb_after_del.json()["entries"]) == 1

        # 关闭无采纳问题后变更 course_id → 409
        q_close_id = str(question_ids[1])
        assert (
            await client.post(
                f"/api/v1/questions/{q_close_id}/close",
                headers=_auth(teacher["token"]),
            )
        ).status_code == 204
        assert (
            await client.patch(
                f"/api/v1/questions/{q_close_id}",
                json={"course_id": None},
                headers=_auth(teacher["token"]),
            )
        ).status_code == 409

        # reputation_ledgers 零同步写入（不依赖 Celery Worker）
        async with session_factory() as session:
            rep_count = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(ReputationLedgerModel)
                        .where(ReputationLedgerModel.user_id.in_(user_ids))
                    )
                ).scalar_one()
            )
            assert rep_count == 0
    finally:
        await _cleanup(course_ids, question_ids, user_ids)


async def test_course_questions_and_leaderboard_concurrency(
    client: httpx.AsyncClient,
) -> None:
    suffix = uuid.uuid4().hex[:6].upper()
    teacher = await _register_and_login(client, role="teacher", nickname="并发教师")
    student1 = await _register_and_login(client, role="student", nickname="并发学生一")
    student2 = await _register_and_login(client, role="student", nickname="并发学生二")
    user_ids = [uuid.UUID(u["id"]) for u in (teacher, student1, student2)]
    course_ids: list[uuid.UUID] = []
    question_ids: list[uuid.UUID] = []

    try:
        c_resp = await client.post(
            "/api/v1/courses",
            json={
                "code": f"CS-CC-{suffix}",
                "name": "并发程序设计",
                "semester": f"2026-Fall-{suffix}",
            },
            headers=_auth(teacher["token"]),
        )
        assert c_resp.status_code == 201
        cid = c_resp.json()["id"]
        course_ids.append(uuid.UUID(cid))

        assert (
            await client.post(
                f"/api/v1/courses/{cid}/enroll", headers=_auth(student1["token"])
            )
        ).status_code == 201

        # 1. 并发提问混合：已选学生(201)、未选学生(403)、教师(201)
        ask_results = await asyncio.gather(
            client.post(
                "/api/v1/questions",
                json={"title": f"并发提问A {suffix}", "body": "已选学生提问", "course_id": cid},
                headers=_auth(student1["token"]),
            ),
            client.post(
                "/api/v1/questions",
                json={"title": f"并发提问B {suffix}", "body": "未选学生提问", "course_id": cid},
                headers=_auth(student2["token"]),
            ),
            client.post(
                "/api/v1/questions",
                json={"title": f"并发提问C {suffix}", "body": "教师提问", "course_id": cid},
                headers=_auth(teacher["token"]),
            ),
        )
        assert [r.status_code for r in ask_results] == [201, 403, 201]
        for r in ask_results:
            if r.status_code == 201:
                question_ids.append(uuid.UUID(r.json()["id"]))

        q_id = ask_results[0].json()["id"]
        # 2. 并发发表多条回答 + 并发投票 + 并发采纳同一问题下的两条回答
        ans_resps = await asyncio.gather(
            client.post(
                f"/api/v1/questions/{q_id}/answers",
                json={"body": "CAS 原子比较并交换实现无锁队列。"},
                headers=_auth(teacher["token"]),
            ),
            client.post(
                f"/api/v1/questions/{q_id}/answers",
                json={"body": "内存屏障保证指令重排可见性。"},
                headers=_auth(student2["token"]),
            ),
        )
        assert all(r.status_code == 201 for r in ans_resps)
        a1_id = ans_resps[0].json()["id"]
        a2_id = ans_resps[1].json()["id"]

        accept_resps = await asyncio.gather(
            client.post(
                f"/api/v1/answers/{a1_id}/accept", headers=_auth(student1["token"])
            ),
            client.post(
                f"/api/v1/answers/{a2_id}/accept", headers=_auth(student1["token"])
            ),
        )
        accept_codes = sorted(r.status_code for r in accept_resps)
        assert accept_codes == [204, 409]

        lb = await client.get(f"/api/v1/courses/{cid}/leaderboard")
        assert lb.status_code == 200
        entries = lb.json()["entries"]
        assert sum(e["accepted_count"] for e in entries) == 1
        assert sum(e["answer_count"] for e in entries) == 2
    finally:
        await _cleanup(course_ids, question_ids, user_ids)
