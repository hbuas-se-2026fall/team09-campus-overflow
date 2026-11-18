"""F11 公开展示名供给面与个人主页集成测试（真实 PG + Redis）。"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from sqlalchemy import delete, event, select, update

from app.contexts.identity.infrastructure.models import (
    RoleModel,
    UserModel,
    UserRoleModel,
)
from app.contexts.identity.infrastructure.user_summary_reader import (
    SqlAlchemyUserSummaryReader,
)
from app.contexts.reputation.domain.ledger import LedgerEntry, LedgerSource
from app.contexts.reputation.infrastructure.models import ReputationLedgerModel
from app.contexts.reputation.infrastructure.repository import (
    SqlAlchemyReputationLedgerRepository,
)
from app.main import create_app
from app.shared.engine import engine, session_factory
from app.shared.redis import get_redis

pytestmark = pytest.mark.integration

BASE_URL = "http://test"

_PRIVACY_FORBIDDEN_KEYS = {
    "email",
    "student_id",
    "staff_id",
    "email_verified",
    "password_hash",
    "created_at",
}


def _is_summary_select(statement: str) -> bool:
    """只匹配 UserSummaryReader / PublicProfileReader 发出的 SQL，排除 CurrentUser 5 表查询。"""
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
    identity_num = (
        str(uuid.uuid4().int)[:10]
        if role == "student"
        else f"T{uuid.uuid4().int % 10_000_000 + 1_000_000}"
    )
    payload: dict[str, Any] = {
        "role": role,
        "email": f"{uuid.uuid4()}@campus.edu.cn",
        "password": "Passw0rd8",
    }
    if role == "student":
        payload["student_id"] = identity_num
    else:
        payload["staff_id"] = identity_num
    reg = await client.post("/api/v1/auth/register", json=payload)
    assert reg.status_code == 201, reg.text
    user_id = str(reg.json()["id"])

    login = await client.post(
        "/api/v1/auth/login",
        json={"identifier": identity_num, "password": "Passw0rd8"},
    )
    assert login.status_code == 200, login.text
    token = str(login.json()["access_token"])

    if nickname is not None:
        patch = await client.patch(
            "/api/v1/auth/me/profile",
            json={"nickname": nickname},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert patch.status_code == 200, patch.text

    return {
        "id": user_id,
        "token": token,
        "identity": identity_num,
        "email": str(payload["email"]),
    }


def _auth(user: dict[str, str]) -> dict[str, str]:
    return {"Authorization": f"Bearer {user['token']}"}


async def _clear_leaderboard_cache() -> None:
    redis = get_redis()
    keys = [key async for key in redis.scan_iter(match="v1:leaderboard:*")]
    if keys:
        await redis.delete(*keys)


@pytest.fixture
async def client(redis_cleanup: None) -> httpx.AsyncClient:
    await _clear_leaderboard_cache()
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as c:
        yield c
    await _clear_leaderboard_cache()


async def test_summary_reader_batch_sql_count_and_dirty_resilience(
    client: httpx.AsyncClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    stu_named = await _register_and_login(client, role="student", nickname="小张")
    stu_plain = await _register_and_login(client, role="student")
    teacher_plain = await _register_and_login(client, role="teacher")
    missing_uid = uuid.uuid4()

    stu_named_uid = uuid.UUID(stu_named["id"])
    stu_plain_uid = uuid.UUID(stu_plain["id"])
    teacher_uid = uuid.UUID(teacher_plain["id"])

    # 1. 空列表发 0 条 SQL
    with _SummarySqlCounter() as counter:
        async with session_factory() as session:
            empty = await SqlAlchemyUserSummaryReader(session).get_summaries([])
            assert empty == {}
    assert len(counter.statements) == 0

    # 2. 批量查询（含重复 ID 与缺失 ID）只发恰好 1 条 SQL
    with _SummarySqlCounter() as counter:
        async with session_factory() as session:
            summaries = await SqlAlchemyUserSummaryReader(session).get_summaries(
                [stu_named_uid, stu_plain_uid, stu_named_uid, teacher_uid, missing_uid]
            )
    assert len(counter.statements) == 1
    assert missing_uid not in summaries
    assert summaries[stu_named_uid].display_name == "小张"
    assert summaries[stu_plain_uid].display_name == f"学生#{stu_plain_uid.hex[:8]}"
    assert summaries[teacher_uid].display_name == f"教师#{teacher_uid.hex[:8]}"

    # 3. 多角色脏数据 + 脏首尾空白昵称：固定优先级取 teacher、记 warning、
    # 不抛 500，且 nickname 与 display_name 一致
    async with session_factory() as session:
        teacher_role_id = (
            await session.execute(
                select(RoleModel.id).where(RoleModel.name == "teacher")
            )
        ).scalar_one()
        session.add(UserRoleModel(user_id=stu_plain_uid, role_id=teacher_role_id))
        await session.execute(
            update(UserModel)
            .where(UserModel.id == stu_plain_uid)
            .values(nickname="  脏空白昵称  ")
        )
        await session.commit()

    try:
        with caplog.at_level(logging.WARNING):
            async with session_factory() as session:
                dirty_summaries = await SqlAlchemyUserSummaryReader(
                    session
                ).get_summaries([stu_plain_uid])
        assert dirty_summaries[stu_plain_uid].role == "teacher"
        assert dirty_summaries[stu_plain_uid].display_name == "脏空白昵称"
        assert "多角色脏数据" in caplog.text

        profile_resp = await client.get(f"/api/v1/users/{stu_plain_uid}/profile")
        assert profile_resp.status_code == 200
        profile_data = profile_resp.json()
        assert profile_data["role"] == "teacher"
        assert profile_data["nickname"] == "脏空白昵称"
        assert profile_data["display_name"] == "脏空白昵称"
    finally:
        async with session_factory() as session:
            teacher_role_id = (
                await session.execute(
                    select(RoleModel.id).where(RoleModel.name == "teacher")
                )
            ).scalar_one()
            await session.execute(
                delete(UserRoleModel).where(
                    UserRoleModel.user_id == stu_plain_uid,
                    UserRoleModel.role_id == teacher_role_id,
                )
            )
            await session.execute(
                update(UserModel)
                .where(UserModel.id == stu_plain_uid)
                .values(nickname=None)
            )
            await session.commit()


async def test_public_user_profile_minimal_disclosure_both_states(
    client: httpx.AsyncClient,
) -> None:
    student = await _register_and_login(client, role="student")
    teacher = await _register_and_login(client, role="teacher")

    patch = await client.patch(
        "/api/v1/auth/me/profile",
        json={"nickname": "陈同学", "college": "计算机学院", "class_name": "软工2401"},
        headers=_auth(student),
    )
    assert patch.status_code == 200

    # 有昵称/学院/班级态（访客免登录）
    resp_full = await client.get(f"/api/v1/users/{student['id']}/profile")
    assert resp_full.status_code == 200
    full_body = resp_full.json()
    assert set(full_body.keys()) == {
        "user_id",
        "role",
        "display_name",
        "nickname",
        "college",
        "class_name",
    }
    assert _PRIVACY_FORBIDDEN_KEYS.isdisjoint(full_body.keys())
    assert full_body == {
        "user_id": student["id"],
        "role": "student",
        "display_name": "陈同学",
        "nickname": "陈同学",
        "college": "计算机学院",
        "class_name": "软工2401",
    }
    assert student["identity"] not in resp_full.text
    assert student["email"] not in resp_full.text

    # 无昵称教师态
    teacher_uid = uuid.UUID(teacher["id"])
    resp_teacher = await client.get(f"/api/v1/users/{teacher['id']}/profile")
    assert resp_teacher.status_code == 200
    teacher_body = resp_teacher.json()
    assert _PRIVACY_FORBIDDEN_KEYS.isdisjoint(teacher_body.keys())
    assert teacher_body == {
        "user_id": teacher["id"],
        "role": "teacher",
        "display_name": f"教师#{teacher_uid.hex[:8]}",
        "nickname": None,
        "college": None,
        "class_name": None,
    }
    assert teacher["identity"] not in resp_teacher.text
    assert teacher["email"] not in resp_teacher.text

    # 不存在 → 404
    missing = await client.get(f"/api/v1/users/{uuid.uuid4()}/profile")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "用户不存在"}


async def test_qa_backfill_sql_counts_and_realtime_nickname_update(
    client: httpx.AsyncClient,
) -> None:
    teacher = await _register_and_login(client, role="teacher")
    student_a = await _register_and_login(client, role="student", nickname="答主A")
    student_b = await _register_and_login(client, role="student")
    teacher_uid = uuid.UUID(teacher["id"])
    stu_b_uid = uuid.UUID(student_b["id"])
    tag_name = f"f11-{uuid.uuid4().hex[:6]}"

    # 写路径额外摘要 SQL == 0
    with _SummarySqlCounter() as counter:
        q1 = await client.post(
            "/api/v1/questions",
            json={
                "title": "F11 展示名集成测试主问题",
                "body": "验证提问/编辑/回答/评论/列表/详情回填",
                "tags": [tag_name],
            },
            headers=_auth(teacher),
        )
        assert q1.status_code == 201, q1.text
        qid = q1.json()["id"]
        assert q1.json()["author_name"] == f"教师#{teacher_uid.hex[:8]}"

        edited = await client.patch(
            f"/api/v1/questions/{qid}",
            json={"title": "F11 展示名集成测试主问题（已编辑）"},
            headers=_auth(teacher),
        )
        assert edited.status_code == 200
        assert edited.json()["author_name"] == f"教师#{teacher_uid.hex[:8]}"

        ans = await client.post(
            f"/api/v1/questions/{qid}/answers",
            json={"body": "学生 A 的回答"},
            headers=_auth(student_a),
        )
        assert ans.status_code == 201
        aid = ans.json()["id"]
        assert ans.json()["author_name"] == "答主A"

        qc = await client.post(
            f"/api/v1/questions/{qid}/comments",
            json={"body": "学生 B 评论问题"},
            headers=_auth(student_b),
        )
        assert qc.status_code == 201
        assert qc.json()["author_name"] == f"学生#{stu_b_uid.hex[:8]}"

        ac = await client.post(
            f"/api/v1/answers/{aid}/comments",
            json={"body": "学生 B 评论回答"},
            headers=_auth(student_b),
        )
        assert ac.status_code == 201
        assert ac.json()["author_name"] == f"学生#{stu_b_uid.hex[:8]}"
    assert len(counter.statements) == 0, counter.statements

    # 再发一个相关问题
    q2 = await client.post(
        "/api/v1/questions",
        json={"title": "F11 相关问题", "body": "同标签推荐", "tags": [tag_name]},
        headers=_auth(student_a),
    )
    assert q2.status_code == 201

    # 列表、详情、相关问题各自恰好 1 条摘要 SQL
    with _SummarySqlCounter() as list_counter:
        list_resp = await client.get("/api/v1/questions", params={"tag": tag_name})
    assert list_resp.status_code == 200
    assert len(list_counter.statements) == 1
    by_id = {item["id"]: item for item in list_resp.json()["items"]}
    assert by_id[qid]["author_name"] == f"教师#{teacher_uid.hex[:8]}"
    assert by_id[q2.json()["id"]]["author_name"] == "答主A"

    with _SummarySqlCounter() as detail_counter:
        detail_resp = await client.get(f"/api/v1/questions/{qid}")
    assert detail_resp.status_code == 200
    assert len(detail_counter.statements) == 1
    detail = detail_resp.json()
    assert detail["author_name"] == f"教师#{teacher_uid.hex[:8]}"
    assert detail["answers"][0]["author_name"] == "答主A"
    assert detail["comments"][0]["author_name"] == f"学生#{stu_b_uid.hex[:8]}"
    assert detail["answers"][0]["comments"][0]["author_name"] == f"学生#{stu_b_uid.hex[:8]}"

    with _SummarySqlCounter() as related_counter:
        rel_resp = await client.get(f"/api/v1/questions/{qid}/related")
    assert rel_resp.status_code == 200
    assert len(related_counter.statements) == 1
    assert rel_resp.json()[0]["author_name"] == "答主A"

    # 教师改昵称后，列表与详情立即生效
    patch_teacher = await client.patch(
        "/api/v1/auth/me/profile",
        json={"nickname": "王教授"},
        headers=_auth(teacher),
    )
    assert patch_teacher.status_code == 200

    detail_after = (await client.get(f"/api/v1/questions/{qid}")).json()
    assert detail_after["author_name"] == "王教授"
    list_after = (
        await client.get("/api/v1/questions", params={"tag": tag_name})
    ).json()["items"]
    assert {item["id"]: item for item in list_after}[qid]["author_name"] == "王教授"


async def test_leaderboard_and_notifications_realtime_nickname_and_sql_count(
    client: httpx.AsyncClient,
) -> None:
    asker = await _register_and_login(client, role="student")
    actor = await _register_and_login(client, role="student", nickname="原昵称")
    teacher = await _register_and_login(client, role="teacher")

    now = datetime.now(UTC)
    base_score = 20_000_000 + int(now.timestamp())
    seeded_events: list[uuid.UUID] = []

    try:
        async with session_factory() as session:
            repo = SqlAlchemyReputationLedgerRepository(session)
            for uid_str, delta in (
                (actor["id"], base_score + 20),
                (teacher["id"], base_score + 10),
            ):
                eid = uuid.uuid4()
                seeded_events.append(eid)
                await repo.append_if_absent(
                    uuid.UUID(uid_str),
                    LedgerEntry(
                        source=LedgerSource.VOTE,
                        event_id=eid,
                        delta=delta,
                        reason="F11 榜单回填测试",
                        occurred_at=now,
                    ),
                )
            await session.commit()

        # 1. 首次查榜（写穿缓存），恰好 1 条摘要 SQL
        with _SummarySqlCounter() as lb_counter_1:
            lb_1 = await client.get("/api/v1/leaderboard", params={"period": "week", "limit": 5})
        assert lb_1.status_code == 200
        assert len(lb_counter_1.statements) == 1
        entries_1 = {e["user_id"]: e for e in lb_1.json()["entries"]}
        assert entries_1[actor["id"]]["display_name"] == "原昵称"
        teacher_uid = uuid.UUID(teacher["id"])
        assert entries_1[teacher["id"]]["display_name"] == f"教师#{teacher_uid.hex[:8]}"

        # 2. 缓存命中期间修改昵称，再次查榜立即生效，且仍恰好 1 条摘要 SQL
        patch_actor = await client.patch(
            "/api/v1/auth/me/profile",
            json={"nickname": "榜单新昵称"},
            headers=_auth(actor),
        )
        assert patch_actor.status_code == 200

        with _SummarySqlCounter() as lb_counter_2:
            lb_2 = await client.get("/api/v1/leaderboard", params={"period": "week", "limit": 5})
        assert lb_2.status_code == 200
        assert len(lb_counter_2.statements) == 1
        entries_2 = {e["user_id"]: e for e in lb_2.json()["entries"]}
        assert entries_2[actor["id"]]["display_name"] == "榜单新昵称"

        # 3. 通知列表回填 actor_name（修改昵称后实时生效，恰好 1 条摘要 SQL）
        q = await client.post(
            "/api/v1/questions",
            json={"title": "通知展示名测试", "body": "验证 actor_name 实时回填"},
            headers=_auth(asker),
        )
        assert q.status_code == 201
        qid = q.json()["id"]
        assert (
            await client.post(
                f"/api/v1/questions/{qid}/answers",
                json={"body": "actor 回复"},
                headers=_auth(actor),
            )
        ).status_code == 201
        assert (
            await client.post(
                f"/api/v1/questions/{qid}/comments",
                json={"body": "teacher 评论"},
                headers=_auth(teacher),
            )
        ).status_code == 201

        with _SummarySqlCounter() as notif_counter:
            notifs_1 = await client.get("/api/v1/notifications", headers=_auth(asker))
        assert notifs_1.status_code == 200
        assert len(notif_counter.statements) == 1
        by_actor_1 = {item["actor_id"]: item["actor_name"] for item in notifs_1.json()["items"]}
        assert by_actor_1[actor["id"]] == "榜单新昵称"
        assert by_actor_1[teacher["id"]] == f"教师#{teacher_uid.hex[:8]}"

        # 修改通知触发者昵称后再次拉取，实时更新
        assert (
            await client.patch(
                "/api/v1/auth/me/profile",
                json={"nickname": "通知新昵称"},
                headers=_auth(actor),
            )
        ).status_code == 200
        notifs_2 = (
            await client.get("/api/v1/notifications", headers=_auth(asker))
        ).json()["items"]
        by_actor_2 = {item["actor_id"]: item["actor_name"] for item in notifs_2}
        assert by_actor_2[actor["id"]] == "通知新昵称"
    finally:
        if seeded_events:
            async with session_factory() as session:
                await session.execute(
                    delete(ReputationLedgerModel).where(
                        ReputationLedgerModel.event_id.in_(seeded_events)
                    )
                )
                await session.commit()
