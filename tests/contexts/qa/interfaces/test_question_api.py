"""提问接口集成测试：httpx ASGI 传输 + 真 PostgreSQL + 真 Redis（登录写 refresh）。

覆盖：201 正常发布（含 strip 端到端）/ 401 未认证 / 422 校验族 / 413 超大 body。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
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


async def _register_and_login(client: httpx.AsyncClient) -> tuple[str, str]:
    """注册并登录，返回 (access_token, user_id)。"""
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
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200, me.text
    return token, me.json()["id"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _question_payload(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": "如何理解数据库第三范式？",
        "body": "教材看不太懂，求举例说明。",
    }
    payload.update(overrides)
    return payload


def _assert_no_input_echo(resp: httpx.Response) -> None:
    """422 不得回显攻击者原始输入：列表形态错误项只许有 type/loc/msg；
    字符串形态（路由捕获 ValueError）时，原始字节中也不许出现 NUL/代理转义。"""
    detail = resp.json()["detail"]
    if isinstance(detail, list):
        for item in detail:
            assert set(item.keys()) == {"type", "loc", "msg"}
    assert b"\x00" not in resp.content and b"\\u0000" not in resp.content
    assert b"\\ud800" not in resp.content


async def test_ask_question_returns_201(client: httpx.AsyncClient) -> None:
    token, user_id = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/questions", json=_question_payload(), headers=_auth(token)
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    # 白名单字段包含公开生命周期状态，无任何内部字段
    assert set(body.keys()) == {"id", "title", "body", "author_id", "created_at", "tags", "status"}
    assert body["tags"] == []  # 未带标签 → 空列表（迭代 4 白名单第 6 字段）
    assert body["status"] == "open"
    assert body["author_id"] == user_id  # 作者取自令牌，非请求体
    assert body["title"] == "如何理解数据库第三范式？"
    uuid.UUID(body["id"])  # id 为合法 UUID


async def test_title_with_surrounding_spaces_is_stripped(client: httpx.AsyncClient) -> None:
    token, _ = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/questions",
        json=_question_payload(title="  带空格的标题  "),
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["title"] == "带空格的标题"


async def test_ask_without_token_returns_401(client: httpx.AsyncClient) -> None:
    resp = await client.post("/api/v1/questions", json=_question_payload())
    assert resp.status_code == 401


async def test_ask_with_bad_token_returns_401(client: httpx.AsyncClient) -> None:
    resp = await client.post(
        "/api/v1/questions", json=_question_payload(), headers=_auth("garbage.token")
    )
    assert resp.status_code == 401


async def test_empty_title_returns_422(client: httpx.AsyncClient) -> None:
    token, _ = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/questions", json=_question_payload(title=""), headers=_auth(token)
    )
    assert resp.status_code == 422


async def test_blank_title_returns_422(client: httpx.AsyncClient) -> None:
    token, _ = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/questions", json=_question_payload(title="    "), headers=_auth(token)
    )
    assert resp.status_code == 422


async def test_title_too_long_returns_422(client: httpx.AsyncClient) -> None:
    token, _ = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/questions",
        json=_question_payload(title="a" * 101),
        headers=_auth(token),
    )
    assert resp.status_code == 422


async def test_body_too_long_returns_422(client: httpx.AsyncClient) -> None:
    token, _ = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/questions",
        json=_question_payload(body="x" * 5001),
        headers=_auth(token),
    )
    assert resp.status_code == 422


async def test_missing_body_returns_422(client: httpx.AsyncClient) -> None:
    token, _ = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/questions", json={"title": "只有标题"}, headers=_auth(token)
    )
    assert resp.status_code == 422


async def test_extra_field_returns_422(client: httpx.AsyncClient) -> None:
    token, _ = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/questions",
        json=_question_payload(hacker=1),
        headers=_auth(token),
    )
    assert resp.status_code == 422


async def test_oversized_body_returns_413(client: httpx.AsyncClient) -> None:
    # body_limit 中间件在路由/鉴权之外层：超限直接 413，不进 schema 校验
    token, _ = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/questions",
        json=_question_payload(body="a" * (1024 * 1024 + 100)),
        headers=_auth(token),
    )
    assert resp.status_code == 413


async def test_nul_in_title_returns_422(client: httpx.AsyncClient) -> None:
    # P-01：NUL 无法存入 PostgreSQL，值对象在落库前拦截（旧行为 500）
    token, _ = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/questions",
        json=_question_payload(title="a\x00b 攻击"),
        headers=_auth(token),
    )
    assert resp.status_code == 422
    _assert_no_input_echo(resp)


async def test_nul_in_body_returns_422(client: httpx.AsyncClient) -> None:
    # P-02：正文 NUL 同样 422
    token, _ = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/questions",
        json=_question_payload(body="x\x00y"),
        headers=_auth(token),
    )
    assert resp.status_code == 422
    _assert_no_input_echo(resp)


async def test_lone_surrogate_title_returns_422(client: httpx.AsyncClient) -> None:
    # P-03：lone surrogate 被 Pydantic 拦截；422 处理器不回显 input，
    # 避免响应体 UTF-8 编码崩溃（旧行为 UnicodeEncodeError → 500）
    token, _ = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/questions",
        content=b'{"title":"\\ud800\\ud800","body":"ok"}',
        headers={**_auth(token), "content-type": "application/json"},
    )
    assert resp.status_code == 422
    _assert_no_input_echo(resp)


async def test_recursive_bomb_returns_422(client: httpx.AsyncClient) -> None:
    # P-04：depth=2000 的 JSON（12KB，绕过 1MB body 上限）；422 处理器不递归
    # 遍历回显 input，避免 jsonable_encoder 爆栈（旧行为 RecursionError → 500）
    token, _ = await _register_and_login(client)
    bomb = b'{"a":' * 2000 + b"1" + b"}" * 2000
    resp = await client.post(
        "/api/v1/questions",
        content=bomb,
        headers={**_auth(token), "content-type": "application/json"},
    )
    assert resp.status_code == 422
    _assert_no_input_echo(resp)


# ============================================================
# 2.5 列表 + 2.6 详情（访客可用，全部无鉴权头）
# ============================================================


async def test_list_guest_access_whitelist(client: httpx.AsyncClient) -> None:
    """S-01/S-12：访客可用；响应与条目均为白名单字段（无正文/密码哈希/内部字段）。"""
    resp = await client.get("/api/v1/questions")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {"items", "total", "page", "page_size", "total_pages"}
    assert data["page"] == 1 and data["page_size"] == 20
    for item in data["items"]:
        assert set(item.keys()) == {"id", "title", "author_id", "created_at", "tags", "status"}
        assert isinstance(item["tags"], list)  # 迭代 4 增量字段（向后兼容）
        assert item["status"] in {"open", "closed"}
    if data["items"]:
        assert data["total_pages"] == -(-data["total"] // data["page_size"])


async def test_list_page_non_positive_returns_422(client: httpx.AsyncClient) -> None:
    """S-02/S-04 族：page 非法 → 422，不 500，不回显输入。"""
    for bad in ("0", "-1"):
        resp = await client.get("/api/v1/questions", params={"page": bad})
        assert resp.status_code == 422
        _assert_no_input_echo(resp)


async def test_list_page_beyond_total_returns_200_empty(client: httpx.AsyncClient) -> None:
    """S-03（约定）：超总页 → 200 空列表，page 原样回显。"""
    resp = await client.get("/api/v1/questions", params={"page": 999999})
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["page"] == 999999


async def test_list_page_size_non_positive_returns_422(client: httpx.AsyncClient) -> None:
    """S-04：page_size ≤ 0 → 422。"""
    for bad in ("0", "-5"):
        resp = await client.get("/api/v1/questions", params={"page_size": bad})
        assert resp.status_code == 422
        _assert_no_input_echo(resp)


async def test_list_page_size_over_limit_422_and_boundary_100_ok(
    client: httpx.AsyncClient,
) -> None:
    """S-05：page_size 上限 100 → 超限 422；边界 100 恰好 200。"""
    for bad in (100000, 101):
        resp = await client.get("/api/v1/questions", params={"page_size": bad})
        assert resp.status_code == 422
        _assert_no_input_echo(resp)
    resp = await client.get("/api/v1/questions", params={"page_size": 100})
    assert resp.status_code == 200
    assert resp.json()["page_size"] == 100


async def test_list_rejects_invalid_sort_param_s07(client: httpx.AsyncClient) -> None:
    """S-07（迭代 2 收紧）：sort 为枚举参数，非法值（含注入串）在参数校验即 422，
    不进 SQL、不回显输入；合法 latest/votes 均 200。"""
    resp = await client.get("/api/v1/questions", params={"sort": "(SELECT 1)"})
    assert resp.status_code == 422
    _assert_no_input_echo(resp)
    for good in ("latest", "votes"):
        resp = await client.get("/api/v1/questions", params={"sort": good})
        assert resp.status_code == 200


async def test_list_pagination_exact_slicing_s08(client: httpx.AsyncClient) -> None:
    """S-08：连发 25 帖（本测试为全表最新块）→ 第 1 页恰为其最新 20 帖，
    第 2 页补足其余 5 帖，跨页不重复。"""
    token, _ = await _register_and_login(client)
    ids: list[str] = []
    for i in range(25):
        r = await client.post(
            "/api/v1/questions",
            json=_question_payload(title=f"S08 分页标题 {i:02d}"),
            headers=_auth(token),
        )
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])

    d1 = (await client.get("/api/v1/questions", params={"page": 1, "page_size": 20})).json()
    assert d1["total"] >= 25 and d1["total_pages"] >= 2
    assert len(d1["items"]) == 20
    ids1 = {item["id"] for item in d1["items"]}
    assert ids1 == set(ids[5:])  # 最新 20 帖（ids[0] 最旧）

    d2 = (await client.get("/api/v1/questions", params={"page": 2, "page_size": 20})).json()
    ids2 = {item["id"] for item in d2["items"]}
    assert set(ids[:5]) <= ids2  # 剩余 5 帖在第 2 页
    assert not ids1 & ids2  # 跨页无重复


async def test_posted_question_immediately_first_in_list(
    client: httpx.AsyncClient,
) -> None:
    """S-14/US-Q04：发布后立即可见且居首（page_size=1 的第 1 项即新帖）。"""
    token, _ = await _register_and_login(client)
    r = await client.post(
        "/api/v1/questions",
        json=_question_payload(title="立即可见标题"),
        headers=_auth(token),
    )
    posted_id = r.json()["id"]
    resp = await client.get("/api/v1/questions", params={"page": 1, "page_size": 1})
    assert resp.status_code == 200
    data = resp.json()
    assert data["page_size"] == 1 and len(data["items"]) == 1
    assert data["items"][0]["id"] == posted_id


async def test_detail_returns_full_whitelist_fields(client: httpx.AsyncClient) -> None:
    """S-09：详情字段完整；tags 迭代 1 恒空；answers/comments 实装（迭代 2/3），
    accepted_answer_id 顶层返回（v3 裁定 #3）。"""
    token, user_id = await _register_and_login(client)
    r = await client.post(
        "/api/v1/questions",
        json=_question_payload(title="详情标题", body="详情正文明细"),
        headers=_auth(token),
    )
    assert r.status_code == 201
    qid = r.json()["id"]
    resp = await client.get(f"/api/v1/questions/{qid}")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {
        "id", "title", "body", "author_id", "created_at",
        "accepted_answer_id", "tags", "status", "answers", "comments",
    }
    assert data["accepted_answer_id"] is None
    assert data["status"] == "open"
    assert data["title"] == "详情标题"
    assert data["body"] == "详情正文明细"
    assert data["author_id"] == user_id
    assert data["tags"] == [] and data["answers"] == []


async def test_detail_missing_returns_404_without_internal_info(
    client: httpx.AsyncClient,
) -> None:
    """S-10：合法 UUID 但不存在 → 404，只回业务语义，无内部错误栈。"""
    resp = await client.get(f"/api/v1/questions/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json() == {"detail": "问题不存在"}
    assert "Traceback" not in resp.text


async def test_detail_invalid_id_returns_422(client: httpx.AsyncClient) -> None:
    """S-11：格式非法 ID → 422（路径校验拦截），不 500。"""
    for bad in ("abc", "not-a-uuid"):
        resp = await client.get(f"/api/v1/questions/{bad}")
        assert resp.status_code == 422
        _assert_no_input_echo(resp)


# ============================================================
# F01 问题筛选（US-Q07）：标签 AND / 状态 / 时间闭区间 / 422 / 分页对账
# ============================================================


async def _create_question_with_tags(
    client: httpx.AsyncClient, token: str, *, title: str, tags: list[str]
) -> str:
    resp = await client.post(
        "/api/v1/questions",
        json=_question_payload(
            title=title,
            body="真实技术讨论：说明背景、已尝试方案与期望结果，便于同学给出可执行建议。",
            tags=tags,
        ),
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_list_filter_multiple_tags_is_and_and_case_insensitive(
    client: httpx.AsyncClient,
) -> None:
    """D3b=AND + D4=按 Tag.key：多标签须同时命中；大小写不敏感；重复传参去重。"""
    token, _ = await _register_and_login(client)
    both = await _create_question_with_tags(
        client,
        token,
        title="React 与 TypeScript 如何组织前端状态？",
        tags=["React", "TypeScript"],
    )
    react_only = await _create_question_with_tags(
        client, token, title="React 组件测试如何选择断言粒度？", tags=["React"]
    )
    unrelated = await _create_question_with_tags(
        client, token, title="PostgreSQL 复合唯一索引如何设计？", tags=["PostgreSQL"]
    )

    params: list[tuple[str, str]] = [
        ("tag", "React"),
        ("tag", "TypeScript"),
        ("page_size", "100"),
    ]
    resp = await client.get("/api/v1/questions", params=params)
    assert resp.status_code == 200, resp.text
    ids = {item["id"] for item in resp.json()["items"]}
    assert both in ids
    assert react_only not in ids  # AND：缺少 TypeScript
    assert unrelated not in ids

    # 大小写不敏感 + 同一 key 重复传参只算一次（D3a/D4）
    dup: list[tuple[str, str]] = [("tag", "react"), ("tag", "REACT"), ("page_size", "100")]
    resp_dup = await client.get("/api/v1/questions", params=dup)
    assert resp_dup.status_code == 200, resp_dup.text
    ids_dup = {item["id"] for item in resp_dup.json()["items"]}
    assert both in ids_dup and react_only in ids_dup


async def test_list_filter_by_status_and_backward_compat(
    client: httpx.AsyncClient,
) -> None:
    """D1：不传 status=全部；open/closed 单条件正确；与 sort=votes 组合 total 同口径。"""
    token, _ = await _register_and_login(client)
    open_id = await _create_question_with_tags(
        client, token, title="React 服务端渲染与客户端缓存如何取舍？", tags=["React"]
    )
    closed_id = await _create_question_with_tags(
        client, token, title="TypeScript 类型体操在业务代码中的边界？", tags=["TypeScript"]
    )
    close = await client.post(
        f"/api/v1/questions/{closed_id}/close", headers=_auth(token)
    )
    assert close.status_code == 204, close.text

    all_resp = await client.get(
        "/api/v1/questions", params={"page_size": 100, "sort": "latest"}
    )
    assert all_resp.status_code == 200
    all_ids = {item["id"] for item in all_resp.json()["items"]}
    assert closed_id in all_ids  # 不传 status 时关闭问题仍在（向后兼容）

    closed_resp = await client.get(
        "/api/v1/questions", params={"status": "closed", "page_size": 100}
    )
    assert closed_resp.status_code == 200, closed_resp.text
    closed_ids = {item["id"] for item in closed_resp.json()["items"]}
    assert closed_id in closed_ids
    assert open_id not in closed_ids

    open_resp = await client.get(
        "/api/v1/questions", params={"status": "open", "page_size": 100}
    )
    assert open_resp.status_code == 200, open_resp.text
    open_ids = {item["id"] for item in open_resp.json()["items"]}
    assert open_id in open_ids
    assert closed_id not in open_ids

    votes_resp = await client.get(
        "/api/v1/questions",
        params={"status": "open", "sort": "votes", "page_size": 100},
    )
    assert votes_resp.status_code == 200, votes_resp.text
    assert votes_resp.json()["total"] == open_resp.json()["total"]


async def test_list_filter_by_closed_time_range(client: httpx.AsyncClient) -> None:
    """D2：时间闭区间 [from, to]；窗口外不命中。"""
    token, _ = await _register_and_login(client)
    qid = await _create_question_with_tags(
        client, token, title="PostgreSQL 事务隔离级别如何选择？", tags=["PostgreSQL"]
    )
    now = datetime.now(UTC)
    inside = await client.get(
        "/api/v1/questions",
        params={
            "created_from": (now - timedelta(minutes=1)).isoformat(),
            "created_to": (now + timedelta(minutes=1)).isoformat(),
            "page_size": 100,
        },
    )
    assert inside.status_code == 200, inside.text
    assert qid in {item["id"] for item in inside.json()["items"]}

    future = await client.get(
        "/api/v1/questions",
        params={"created_from": (now + timedelta(hours=1)).isoformat(), "page_size": 100},
    )
    assert future.status_code == 200, future.text
    assert qid not in {item["id"] for item in future.json()["items"]}


async def test_list_filter_invalid_params_return_422(client: httpx.AsyncClient) -> None:
    """非法 status / 空 tag / naive 时间 / 逆序区间 / 非法时间格式 → 422，不回显输入。"""
    cases: list[dict[str, str]] = [
        {"status": "bogus"},
        {"tag": ""},
        {"created_from": "2026-01-01T00:00:00"},
        {
            "created_from": "2026-02-01T00:00:00+08:00",
            "created_to": "2026-01-01T00:00:00+08:00",
        },
        {"created_to": "not-a-date"},
    ]
    for params in cases:
        resp = await client.get("/api/v1/questions", params=params)
        assert resp.status_code == 422, (params, resp.text)
        _assert_no_input_echo(resp)


async def test_list_filter_pagination_total_consistent(
    client: httpx.AsyncClient,
) -> None:
    """F01 核心验收：COUNT 与当前页同口径——total/分页切片与筛选结果严格一致。"""
    token, _ = await _register_and_login(client)
    titles = (
        "React 并发渲染下状态管理的取舍",
        "TypeScript 泛型约束与组件 Props 设计",
        "PostgreSQL 唯一索引与并发热点写入",
    )
    chain = ["React", "TypeScript", "PostgreSQL"]
    created = [
        await _create_question_with_tags(client, token, title=title, tags=chain)
        for title in titles
    ]

    base: list[tuple[str, str]] = [
        ("tag", "React"),
        ("tag", "TypeScript"),
        ("tag", "PostgreSQL"),
        ("sort", "latest"),
    ]
    full = await client.get(
        "/api/v1/questions", params=[*base, ("page", "1"), ("page_size", "100")]
    )
    assert full.status_code == 200, full.text
    total = full.json()["total"]
    assert total >= len(created)
    assert full.json()["total_pages"] == -(-total // 100)

    d1 = await client.get(
        "/api/v1/questions", params=[*base, ("page", "1"), ("page_size", "2")]
    )
    d2 = await client.get(
        "/api/v1/questions", params=[*base, ("page", "2"), ("page_size", "2")]
    )
    for resp in (d1, d2):
        assert resp.status_code == 200, resp.text
        assert resp.json()["total"] == total
        assert resp.json()["total_pages"] == -(-total // 2)
    ids1 = {item["id"] for item in d1.json()["items"]}
    ids2 = {item["id"] for item in d2.json()["items"]}
    assert not ids1 & ids2  # 跨页无重复
    # 新发 3 帖是全表最新，必然落在前两页
    assert set(created) <= ids1 | ids2


async def test_list_filter_too_many_distinct_tags_returns_422(
    client: httpx.AsyncClient,
) -> None:
    """评审加固：去重后 >5 个 tag key → 422；重复传参去重后 ≤5 → 200。"""
    too_many: list[tuple[str, str]] = [
        ("tag", t) for t in ("alpha", "beta", "gamma", "delta", "epsilon", "zeta")
    ]
    resp = await client.get("/api/v1/questions", params=too_many)
    assert resp.status_code == 422, resp.text
    _assert_no_input_echo(resp)

    dedup_ok: list[tuple[str, str]] = [
        ("tag", t)
        for t in ("React", "react", "React", "TypeScript", "React", "PostgreSQL")
    ]
    ok = await client.get("/api/v1/questions", params=dedup_ok)
    assert ok.status_code == 200, ok.text


# ============================================================
# F02 全文搜索（ILIKE）：标题/正文命中、大小写、通配符字面、组合、422
# ============================================================


async def _create_question(
    client: httpx.AsyncClient, token: str, *, title: str, body: str
) -> str:
    resp = await client.post(
        "/api/v1/questions",
        json=_question_payload(title=title, body=body),
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def test_list_search_matches_title_and_body(
    client: httpx.AsyncClient,
) -> None:
    """F02：标题命中、正文命中；无关问题不命中；无命中返回 200 + 空列表。"""
    token, _ = await _register_and_login(client)
    word = f"F02{uuid.uuid4().hex[:8]}"
    title_hit = await _create_question(
        client, token, title=f"{word} 标题命中", body="普通正文"
    )
    body_hit = await _create_question(
        client, token, title="普通标题", body=f"正文包含 {word}"
    )
    unrelated = await _create_question(
        client, token, title="无关标题", body="无关正文"
    )

    resp = await client.get("/api/v1/questions", params={"q": word, "page_size": 100})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    ids = {item["id"] for item in data["items"]}
    assert {title_hit, body_hit} <= ids
    assert unrelated not in ids
    assert data["total"] == len(data["items"])

    miss = await client.get(
        "/api/v1/questions", params={"q": f"{word}不存在", "page_size": 100}
    )
    assert miss.status_code == 200, miss.text
    assert miss.json()["items"] == []
    assert miss.json()["total"] == 0


async def test_list_search_case_insensitive_and_blank_equals_absent(
    client: httpx.AsyncClient,
) -> None:
    """F02：ILIKE 大小写不敏感；空串/纯空白等价于不传（total 与无参一致）。"""
    token, _ = await _register_and_login(client)
    word = f"F02{uuid.uuid4().hex[:8]}"
    qid = await _create_question(
        client, token, title=f"{word} SQLAlchemy 事务", body="正文"
    )

    hit = await client.get(
        "/api/v1/questions",
        params={"q": f"{word} sqlalchemy", "page_size": 100},
    )
    assert hit.status_code == 200, hit.text
    assert qid in {item["id"] for item in hit.json()["items"]}

    baseline = await client.get("/api/v1/questions", params={"page_size": 100})
    blank = await client.get("/api/v1/questions", params={"q": "   ", "page_size": 100})
    assert baseline.status_code == blank.status_code == 200
    assert blank.json()["total"] == baseline.json()["total"]


async def test_list_search_wildcards_are_literal(client: httpx.AsyncClient) -> None:
    """F02：% 按字面匹配（端到端验证 escape_like 与 escape 参数成对）。"""
    token, _ = await _register_and_login(client)
    word = f"F02{uuid.uuid4().hex[:8]}"
    hit = await _create_question(
        client, token, title=f"{word} 100% 命中", body="正文"
    )
    await _create_question(client, token, title=f"{word} 100x 不应命中", body="正文")

    resp = await client.get(
        "/api/v1/questions", params={"q": f"{word} 100%", "page_size": 100}
    )
    assert resp.status_code == 200, resp.text
    assert {item["id"] for item in resp.json()["items"]} == {hit}


async def test_list_search_combines_with_tag_filter(client: httpx.AsyncClient) -> None:
    """F02 与 F01 组合：q + tag 同时生效，total 与当前页同口径。"""
    token, _ = await _register_and_login(client)
    word = f"F02{uuid.uuid4().hex[:8]}"
    react_id = await _create_question_with_tags(
        client, token, title=f"{word} React 状态管理", tags=["React"]
    )
    pg_id = await _create_question_with_tags(
        client, token, title=f"{word} PostgreSQL 索引", tags=["PostgreSQL"]
    )

    resp = await client.get(
        "/api/v1/questions",
        params=[("q", word), ("tag", "React"), ("page_size", "100")],
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    ids = {item["id"] for item in data["items"]}
    assert react_id in ids
    assert pg_id not in ids
    assert data["total"] == len(data["items"])


async def test_list_search_invalid_q_returns_422(client: httpx.AsyncClient) -> None:
    """F02：超 100 字、含制表符 → 422，不回显原始输入。"""
    cases = [{"q": "a" * 101}, {"q": "React\tHooks"}]
    for params in cases:
        resp = await client.get("/api/v1/questions", params=params)
        assert resp.status_code == 422, (params, resp.text)
        _assert_no_input_echo(resp)


# ============================================================
# F03 相关问题推荐：标签共现排序 / limit 边界 / 404 / 无标签空
# ============================================================


async def test_related_questions_ordered_by_tag_overlap(
    client: httpx.AsyncClient,
) -> None:
    """200：标签重合数降序；自身不出现在推荐里。"""
    token, _ = await _register_and_login(client)
    base = f"F03{uuid.uuid4().hex[:8]}"
    tag_a, tag_b = f"{base}React", f"{base}TypeScript"
    source = await _create_question_with_tags(
        client, token, title="相关问题种子：React 与 TypeScript", tags=[tag_a, tag_b]
    )
    full = await _create_question_with_tags(
        client, token, title="两个标签都重合的候选", tags=[tag_a, tag_b]
    )
    half = await _create_question_with_tags(
        client, token, title="仅一个标签重合的候选", tags=[tag_a]
    )

    resp = await client.get(f"/api/v1/questions/{source}/related")
    assert resp.status_code == 200, resp.text
    ids = [item["id"] for item in resp.json()]
    assert ids == [full, half]
    assert source not in ids


async def test_related_questions_limit_bounds_return_422(
    client: httpx.AsyncClient,
) -> None:
    """limit 边界：0 与 11 均 422（Query ge=1/le=10）。"""
    token, _ = await _register_and_login(client)
    source = await _create_question_with_tags(
        client, token, title="相关问题 limit 边界种子", tags=[]
    )
    for limit in (0, 11):
        resp = await client.get(
            f"/api/v1/questions/{source}/related", params={"limit": limit}
        )
        assert resp.status_code == 422, (limit, resp.text)


async def test_related_questions_missing_returns_404(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get(f"/api/v1/questions/{uuid.uuid4()}/related")
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "问题不存在"
    assert "traceback" not in resp.text.lower()


async def test_related_questions_without_tags_returns_empty(
    client: httpx.AsyncClient,
) -> None:
    """无标签问题返回 200 空数组（非 404/非错误）。"""
    token, _ = await _register_and_login(client)
    source = await _create_question_with_tags(
        client, token, title="无标签问题不应有相关推荐", tags=[]
    )

    resp = await client.get(f"/api/v1/questions/{source}/related")
    assert resp.status_code == 200, resp.text
    assert resp.json() == []
