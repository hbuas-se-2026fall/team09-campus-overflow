"""F10 Redis 验证码存储与发送器适配器单元测试（纯内存，进 CI）。"""

from __future__ import annotations

import smtplib
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from redis.exceptions import RedisError

from app.config.settings import DEFAULT_EMAIL_VERIFY_HMAC_SECRET, Settings, get_settings
from app.contexts.identity.application.ports import VerificationResult
from app.contexts.identity.domain.errors import (
    EmailVerificationUnavailableError,
    VerificationCooldownError,
)
from app.contexts.identity.infrastructure.email_sender import (
    DevLogVerificationCodeSender,
    SmtpVerificationCodeSender,
    UnconfiguredVerificationCodeSender,
    build_verification_code_sender,
)
from app.contexts.identity.infrastructure.email_verification_store import (
    RedisEmailVerificationStore,
)
from app.contexts.identity.interfaces.api.error_mapping import (
    register_identity_error_handlers,
)
from app.main import create_app


class FakeLuaRedis:
    """模拟 RedisEmailVerificationStore 依赖的 3 条 Lua 脚本语义。"""

    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.fail = False

    async def eval(self, script: str, numkeys: int, *args: Any) -> Any:
        if self.fail:
            raise RedisError("redis down")
        if "EXISTS" in script:
            cd_key, code_key = str(args[0]), str(args[1])
            token, code_hash = str(args[2]), str(args[4])
            if cd_key in self.kv:
                return 0
            self.kv[cd_key] = token
            self.hashes[code_key] = {
                "hash": code_hash,
                "attempts": "0",
                "token": token,
            }
            return 1
        if "HGET" in script and "DEL" in script and "HINCRBY" not in script:
            cd_key, code_key, token = str(args[0]), str(args[1]), str(args[2])
            if self.kv.get(cd_key) == token:
                self.kv.pop(cd_key, None)
            if self.hashes.get(code_key, {}).get("token") == token:
                self.hashes.pop(code_key, None)
            return 1
        code_key, code_hash, max_attempts = str(args[0]), str(args[1]), int(args[2])
        entry = self.hashes.get(code_key)
        if not entry or "hash" not in entry:
            return "expired"
        if entry["hash"] == code_hash:
            return "ok"
        attempts = int(entry["attempts"]) + 1
        entry["attempts"] = str(attempts)
        if attempts >= max_attempts:
            self.hashes.pop(code_key, None)
            return "too_many"
        return "invalid"


async def test_store_stores_hmac_only_and_enforces_cooldown_and_five_attempts() -> None:
    fake = FakeLuaRedis()
    store = RedisEmailVerificationStore("test-hmac-secret", lambda: fake)  # type: ignore[arg-type,return-value]
    uid = uuid4()

    token = await store.prepare_send(uid, "654321", cooldown_seconds=60, code_ttl_seconds=900)
    assert token
    # Redis 内不出现明文 6 位验证码
    all_values = list(fake.kv.values()) + [
        v for h in fake.hashes.values() for v in h.values()
    ]
    assert "654321" not in all_values

    with pytest.raises(VerificationCooldownError):
        await store.prepare_send(uid, "111111", cooldown_seconds=60, code_ttl_seconds=900)

    for _ in range(4):
        assert await store.verify(uid, "000000", max_attempts=5) is VerificationResult.INVALID
    assert await store.verify(uid, "000000", max_attempts=5) is VerificationResult.TOO_MANY
    assert await store.verify(uid, "654321", max_attempts=5) is VerificationResult.EXPIRED


async def test_store_rollback_compare_and_delete_ignores_newer_token() -> None:
    fake = FakeLuaRedis()
    store = RedisEmailVerificationStore("test-hmac-secret", lambda: fake)  # type: ignore[arg-type,return-value]
    uid = uuid4()

    old_token = await store.prepare_send(uid, "111111", cooldown_seconds=60, code_ttl_seconds=900)
    # 模拟冷却已过期后新请求写入新 token
    fake.kv.pop(f"email_verify:cd:{uid}", None)
    new_token = await store.prepare_send(uid, "222222", cooldown_seconds=60, code_ttl_seconds=900)

    # 旧请求的回滚绝不能删除新请求的 cd 和 code
    await store.rollback_send(uid, old_token)
    assert f"email_verify:cd:{uid}" in fake.kv
    assert await store.verify(uid, "222222", max_attempts=5) is VerificationResult.OK

    # 匹配 token 才回滚双键
    await store.rollback_send(uid, new_token)
    assert f"email_verify:cd:{uid}" not in fake.kv
    assert await store.verify(uid, "222222", max_attempts=5) is VerificationResult.EXPIRED


async def test_store_translates_redis_error_to_503_exception() -> None:
    fake = FakeLuaRedis()
    fake.fail = True
    store = RedisEmailVerificationStore("test-hmac-secret", lambda: fake)  # type: ignore[arg-type,return-value]
    uid = uuid4()

    with pytest.raises(EmailVerificationUnavailableError):
        await store.prepare_send(uid, "123456", cooldown_seconds=60, code_ttl_seconds=900)
    with pytest.raises(EmailVerificationUnavailableError):
        await store.verify(uid, "123456", max_attempts=5)
    # rollback 失败静默记录 warning，不抛异常掩盖主异常
    await store.rollback_send(uid, "tok")


def test_sender_builder_respects_app_env_and_smtp_completeness() -> None:
    assert isinstance(
        build_verification_code_sender(Settings(app_env="dev")),
        DevLogVerificationCodeSender,
    )
    assert isinstance(
        build_verification_code_sender(Settings(app_env="test")),
        DevLogVerificationCodeSender,
    )
    assert isinstance(
        build_verification_code_sender(Settings(app_env="prod")),
        UnconfiguredVerificationCodeSender,
    )
    # 半套 SMTP（有 host 缺 from_email，或有 username 缺 password）按未配置处理
    assert isinstance(
        build_verification_code_sender(Settings(app_env="prod", smtp_host="smtp.example.com")),
        UnconfiguredVerificationCodeSender,
    )
    assert isinstance(
        build_verification_code_sender(
            Settings(
                app_env="prod",
                smtp_host="smtp.example.com",
                smtp_from_email="no-reply@example.com",
                smtp_username="user",
                smtp_password="",
            )
        ),
        UnconfiguredVerificationCodeSender,
    )
    assert isinstance(
        build_verification_code_sender(
            Settings(
                app_env="prod",
                smtp_host="smtp.example.com",
                smtp_from_email="no-reply@example.com",
            )
        ),
        SmtpVerificationCodeSender,
    )


async def test_smtp_sender_uses_timeout_and_translates_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @dataclass
    class _Captured:
        timeout: float | None = None

    captured = _Captured()

    class _FailingSMTP:
        def __init__(self, host: str, port: int, *, timeout: float) -> None:
            captured.timeout = timeout

        def __enter__(self) -> _FailingSMTP:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def starttls(self) -> None:
            raise smtplib.SMTPException("tls failed")

    monkeypatch.setattr(smtplib, "SMTP", _FailingSMTP)
    sender = SmtpVerificationCodeSender(
        host="smtp.example.com",
        port=587,
        from_email="no-reply@example.com",
        timeout_seconds=7.5,
    )
    with pytest.raises(EmailVerificationUnavailableError):
        await sender.send("stu@edu.cn", "123456")
    assert captured.timeout == 7.5


def test_prod_default_hmac_secret_fails_fast_at_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("EMAIL_VERIFY_HMAC_SECRET", DEFAULT_EMAIL_VERIFY_HMAC_SECRET)
    get_settings.cache_clear()
    try:
        with pytest.raises(RuntimeError, match="email_verify_hmac_secret"):
            create_app()
    finally:
        get_settings.cache_clear()


def test_email_verification_unavailable_maps_to_503_not_422() -> None:
    app = FastAPI()
    register_identity_error_handlers(app)

    @app.get("/unavailable")
    def _unavailable() -> None:
        raise EmailVerificationUnavailableError("服务不可用")

    resp = TestClient(app, raise_server_exceptions=False).get("/unavailable")
    assert resp.status_code == 503
    assert resp.json() == {"detail": "服务不可用"}
