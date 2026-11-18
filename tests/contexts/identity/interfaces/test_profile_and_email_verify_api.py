"""F10 校园资料扩展与邮箱验证集成测试：真实 PG + 真实 Redis。"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from redis.exceptions import RedisError

from app.config.settings import Settings
from app.contexts.identity.infrastructure.email_sender import build_verification_code_sender
from app.contexts.identity.infrastructure.email_verification_store import (
    RedisEmailVerificationStore,
)
from app.contexts.identity.interfaces.api.deps import (
    get_email_verification_store,
    get_verification_code_sender,
)
from app.main import create_app
from app.shared.redis import get_redis

pytestmark = pytest.mark.integration

BASE_URL = "http://test"


class _CapturingSender:
    def __init__(self) -> None:
        self.codes: list[tuple[str, str]] = []

    async def send(self, email: str, code: str) -> None:
        self.codes.append((email, code))


async def _register_and_login(
    client: httpx.AsyncClient,
) -> tuple[str, str, str, str]:
    email = f"{uuid.uuid4()}@stu.edu.cn"
    student_id = str(uuid.uuid4().int)[:10]
    reg = await client.post(
        "/api/v1/auth/register",
        json={
            "role": "student",
            "email": email,
            "password": "Passw0rd8",
            "student_id": student_id,
        },
    )
    assert reg.status_code == 201, reg.text
    user_id = str(reg.json()["id"])
    login = await client.post(
        "/api/v1/auth/login",
        json={"identifier": student_id, "password": "Passw0rd8"},
    )
    assert login.status_code == 200, login.text
    return user_id, email, str(login.json()["access_token"]), student_id


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
async def client_with_sender(
    redis_cleanup: None,
) -> tuple[httpx.AsyncClient, _CapturingSender]:
    sender = _CapturingSender()
    app = create_app()
    app.dependency_overrides[get_verification_code_sender] = lambda: sender
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as c:
        yield c, sender


async def test_profile_patch_partial_clear_empty_422_and_duplicate_nickname(
    client_with_sender: tuple[httpx.AsyncClient, _CapturingSender],
) -> None:
    client, _ = client_with_sender
    _, _, token1, _ = await _register_and_login(client)
    _, _, token2, _ = await _register_and_login(client)

    empty = await client.patch("/api/v1/auth/me/profile", headers=_auth(token1), json={})
    assert empty.status_code == 422

    bad = await client.patch(
        "/api/v1/auth/me/profile",
        headers=_auth(token1),
        json={"nickname": "   "},
    )
    assert bad.status_code == 422

    p1 = await client.patch(
        "/api/v1/auth/me/profile",
        headers=_auth(token1),
        json={"nickname": "  同款昵称  ", "college": "计算机学院", "class_name": "软工2401"},
    )
    assert p1.status_code == 200, p1.text
    body1 = p1.json()
    assert body1["nickname"] == "同款昵称"
    assert body1["college"] == "计算机学院"
    assert body1["class_name"] == "软工2401"
    assert body1["email_verified"] is False

    # 显式 null 清空 college，未传 nickname/class_name 保持不变
    p2 = await client.patch(
        "/api/v1/auth/me/profile",
        headers=_auth(token1),
        json={"college": None},
    )
    assert p2.status_code == 200, p2.text
    assert p2.json()["nickname"] == "同款昵称"
    assert p2.json()["college"] is None
    assert p2.json()["class_name"] == "软工2401"

    # 允许昵称重名
    dup = await client.patch(
        "/api/v1/auth/me/profile",
        headers=_auth(token2),
        json={"nickname": "同款昵称"},
    )
    assert dup.status_code == 200, dup.text
    assert dup.json()["nickname"] == "同款昵称"


async def test_email_verify_send_hmac_storage_cooldown_and_already_verified(
    client_with_sender: tuple[httpx.AsyncClient, _CapturingSender],
) -> None:
    client, sender = client_with_sender
    user_id, email, token, _ = await _register_and_login(client)

    # 并发 5 次 send：恰 1 次 204，其余 4 次 429
    responses = await asyncio.gather(
        *[
            client.post("/api/v1/auth/me/verify-email/send", headers=_auth(token))
            for _ in range(5)
        ]
    )
    statuses = sorted(r.status_code for r in responses)
    assert statuses == [204, 429, 429, 429, 429]
    assert len(sender.codes) == 1
    sent_email, code = sender.codes[0]
    assert sent_email == email

    # Redis 中绝不存明文 6 位码，只存 HMAC
    redis = get_redis()
    cd_val = await redis.get(f"email_verify:cd:{user_id}")
    code_hash_fields: dict[str, Any] = await redis.hgetall(f"email_verify:code:{user_id}")
    assert cd_val is not None and code not in str(cd_val)
    assert "hash" in code_hash_fields
    assert code not in code_hash_fields.values()

    # 确认验证成功 → 204
    confirm = await client.post(
        "/api/v1/auth/me/verify-email/confirm",
        headers=_auth(token),
        json={"code": code},
    )
    assert confirm.status_code == 204, confirm.text

    # 已验证用户再次 send → 409；再次 confirm → 204（幂等）
    again_send = await client.post(
        "/api/v1/auth/me/verify-email/send", headers=_auth(token)
    )
    assert again_send.status_code == 409
    again_confirm = await client.post(
        "/api/v1/auth/me/verify-email/confirm",
        headers=_auth(token),
        json={"code": "000000"},
    )
    assert again_confirm.status_code == 204


async def test_email_verify_concurrent_confirm_both_204_and_no_patch_lost_update(
    client_with_sender: tuple[httpx.AsyncClient, _CapturingSender],
) -> None:
    client, sender = client_with_sender
    _, _, token, _ = await _register_and_login(client)
    send_resp = await client.post(
        "/api/v1/auth/me/verify-email/send", headers=_auth(token)
    )
    assert send_resp.status_code == 204
    _, code = sender.codes[0]

    # 并发双 confirm + 并发 PATCH 资料：confirm 均 204 且不覆盖 PATCH
    c1, c2, p = await asyncio.gather(
        client.post(
            "/api/v1/auth/me/verify-email/confirm",
            headers=_auth(token),
            json={"code": code},
        ),
        client.post(
            "/api/v1/auth/me/verify-email/confirm",
            headers=_auth(token),
            json={"code": code},
        ),
        client.patch(
            "/api/v1/auth/me/profile",
            headers=_auth(token),
            json={"nickname": "并发保留昵称"},
        ),
    )
    assert c1.status_code == 204
    assert c2.status_code == 204
    assert p.status_code == 200

    me = await client.get("/api/v1/auth/me", headers=_auth(token))
    assert me.status_code == 200
    assert me.json()["email_verified"] is True
    assert me.json()["nickname"] == "并发保留昵称"


async def test_email_verify_expired_and_five_wrong_attempts(
    client_with_sender: tuple[httpx.AsyncClient, _CapturingSender],
) -> None:
    client, sender = client_with_sender
    user_id, _, token, _ = await _register_and_login(client)

    # 未发送 / 已过期 → 400
    expired = await client.post(
        "/api/v1/auth/me/verify-email/confirm",
        headers=_auth(token),
        json={"code": "123456"},
    )
    assert expired.status_code == 400

    assert (
        await client.post("/api/v1/auth/me/verify-email/send", headers=_auth(token))
    ).status_code == 204
    _, real_code = sender.codes[0]
    wrong_code = "000000" if real_code != "000000" else "999999"

    # 连续 5 次错码 → 均 400，第 5 次作废删码
    for _ in range(5):
        resp = await client.post(
            "/api/v1/auth/me/verify-email/confirm",
            headers=_auth(token),
            json={"code": wrong_code},
        )
        assert resp.status_code == 400

    assert await get_redis().hgetall(f"email_verify:code:{user_id}") == {}
    # 随后即使提交原正确码仍 400
    after_void = await client.post(
        "/api/v1/auth/me/verify-email/confirm",
        headers=_auth(token),
        json={"code": real_code},
    )
    assert after_void.status_code == 400


async def test_email_verify_send_rollback_on_smtp_failure_and_prod_unconfigured_503(
    redis_cleanup: None,
) -> None:
    app = create_app()
    # app_env=prod 且未配 SMTP → 503，且回滚 cd 与 code
    app.dependency_overrides[get_verification_code_sender] = lambda: build_verification_code_sender(
        Settings(app_env="prod")
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as c:
        user_id, _, token, _ = await _register_and_login(c)
        resp = await c.post("/api/v1/auth/me/verify-email/send", headers=_auth(token))
        assert resp.status_code == 503
        redis = get_redis()
        assert await redis.get(f"email_verify:cd:{user_id}") is None
        assert await redis.hgetall(f"email_verify:code:{user_id}") == {}

        # 修复发送器后无需等 60s 可立即重发成功 204
        sender = _CapturingSender()
        app.dependency_overrides[get_verification_code_sender] = lambda: sender
        retry = await c.post("/api/v1/auth/me/verify-email/send", headers=_auth(token))
        assert retry.status_code == 204


async def test_email_verify_redis_outage_returns_503(redis_cleanup: None) -> None:
    class _BrokenRedis:
        async def eval(self, *args: object, **kwargs: object) -> Any:
            raise RedisError("redis down")

    app = create_app()
    app.dependency_overrides[get_email_verification_store] = lambda: RedisEmailVerificationStore(
        "test-secret",
        lambda: _BrokenRedis(),  # type: ignore[arg-type,return-value]
    )
    app.dependency_overrides[get_verification_code_sender] = lambda: _CapturingSender()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as c:
        _, _, token, _ = await _register_and_login(c)
        r_send = await c.post("/api/v1/auth/me/verify-email/send", headers=_auth(token))
        assert r_send.status_code == 503
        r_confirm = await c.post(
            "/api/v1/auth/me/verify-email/confirm",
            headers=_auth(token),
            json={"code": "123456"},
        )
        assert r_confirm.status_code == 503
