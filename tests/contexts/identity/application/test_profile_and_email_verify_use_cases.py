"""F10 资料更新与邮箱验证用例单元测试（纯内存 fake，不连库不连 Redis，进 CI）。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.contexts.identity.application.commands import (
    ConfirmEmailVerificationCommand,
    SendEmailVerificationCommand,
    UpdateProfileCommand,
)
from app.contexts.identity.application.confirm_email_verification_use_case import (
    ConfirmEmailVerificationUseCase,
)
from app.contexts.identity.application.ports import VerificationResult
from app.contexts.identity.application.send_email_verification_use_case import (
    SendEmailVerificationUseCase,
)
from app.contexts.identity.application.update_profile_use_case import UpdateProfileUseCase
from app.contexts.identity.domain.errors import (
    EmailAlreadyVerifiedError,
    EmailVerificationUnavailableError,
    InvalidCredentialsError,
    InvalidVerificationCodeError,
    VerificationCooldownError,
)
from app.contexts.identity.domain.user import User
from app.contexts.identity.domain.value_objects import (
    ClassName,
    College,
    Email,
    Nickname,
    PasswordHash,
    StudentId,
)
from app.shared.errors import DomainValidationError
from app.shared.sentinel import UNSET, UnsetType


def _make_user(*, verified: bool = False) -> User:
    return User(
        id=uuid4(),
        role="student",
        email=Email("zhang@stu.edu.cn"),
        password_hash=PasswordHash("$2b$12$abcdefghijklmnopqrstuv"),
        student_id=StudentId("2025010101"),
        staff_id=None,
        created_at=datetime.now(UTC),
        nickname=Nickname("旧昵称"),
        college=College("信息学院"),
        class_name=ClassName("2401"),
        email_verified=verified,
    )


class FakeUserRepo:
    def __init__(self, user: User | None) -> None:
        self.user = user
        self.last_for_update: bool | None = None
        self.verified_calls = 0

    async def get_by_id(
        self, user_id: UUID, *, for_update: bool = False
    ) -> User | None:
        self.last_for_update = for_update
        if self.user is not None and self.user.id == user_id:
            return self.user
        return None

    async def update_profile(
        self,
        user_id: UUID,
        *,
        nickname: Nickname | None | UnsetType = UNSET,
        college: College | None | UnsetType = UNSET,
        class_name: ClassName | None | UnsetType = UNSET,
    ) -> User | None:
        if self.user is None or self.user.id != user_id:
            return None
        self.user.update_profile(
            nickname=nickname, college=college, class_name=class_name
        )
        return self.user

    async def mark_email_verified(self, user_id: UUID) -> None:
        self.verified_calls += 1
        if self.user is not None and self.user.id == user_id:
            self.user.mark_email_verified()


class FakeVerificationStore:
    def __init__(self) -> None:
        self.codes: dict[UUID, str] = {}
        self.tokens: dict[UUID, str] = {}
        self.rolled_back: list[tuple[UUID, str]] = []
        self.in_cooldown = False
        self.next_result = VerificationResult.OK
        self.verify_calls = 0

    async def prepare_send(
        self,
        user_id: UUID,
        code: str,
        *,
        cooldown_seconds: int,
        code_ttl_seconds: int,
    ) -> str:
        if self.in_cooldown:
            raise VerificationCooldownError("冷却中")
        token = f"tok-{len(self.tokens) + 1}"
        self.codes[user_id] = code
        self.tokens[user_id] = token
        return token

    async def rollback_send(self, user_id: UUID, send_token: str) -> None:
        self.rolled_back.append((user_id, send_token))
        if self.tokens.get(user_id) == send_token:
            self.tokens.pop(user_id, None)
            self.codes.pop(user_id, None)

    async def verify(
        self,
        user_id: UUID,
        code: str,
        *,
        max_attempts: int,
    ) -> VerificationResult:
        self.verify_calls += 1
        if self.next_result is not VerificationResult.OK:
            return self.next_result
        return (
            VerificationResult.OK
            if self.codes.get(user_id) == code
            else VerificationResult.INVALID
        )


class FakeCodeSender:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.sent: list[tuple[str, str]] = []

    async def send(self, email: str, code: str) -> None:
        if self.fail:
            raise EmailVerificationUnavailableError("SMTP 故障")
        self.sent.append((email, code))


async def test_update_profile_partial_and_explicit_clear() -> None:
    user = _make_user()
    repo = FakeUserRepo(user)
    use_case = UpdateProfileUseCase(repo)

    updated = await use_case.execute(
        UpdateProfileCommand(user_id=user.id, nickname="  新昵称  ", college=None)
    )
    assert updated.nickname == Nickname("新昵称")
    assert updated.college is None
    assert updated.class_name == ClassName("2401")
    assert updated.email_verified is False


async def test_update_profile_rejects_empty_and_invalid_and_missing_user() -> None:
    user = _make_user()
    use_case = UpdateProfileUseCase(FakeUserRepo(user))

    with pytest.raises(DomainValidationError):
        await use_case.execute(UpdateProfileCommand(user_id=user.id))
    with pytest.raises(DomainValidationError):
        await use_case.execute(UpdateProfileCommand(user_id=user.id, nickname="   "))

    missing_uc = UpdateProfileUseCase(FakeUserRepo(None))
    with pytest.raises(InvalidCredentialsError):
        await missing_uc.execute(UpdateProfileCommand(user_id=user.id, nickname="测试"))


async def test_send_verification_success_and_already_verified_and_cooldown() -> None:
    user = _make_user(verified=False)
    store = FakeVerificationStore()
    sender = FakeCodeSender()
    uc = SendEmailVerificationUseCase(FakeUserRepo(user), store, sender)

    await uc.execute(SendEmailVerificationCommand(user_id=user.id))
    assert len(sender.sent) == 1
    assert len(sender.sent[0][1]) == 6 and sender.sent[0][1].isdigit()

    store.in_cooldown = True
    with pytest.raises(VerificationCooldownError):
        await uc.execute(SendEmailVerificationCommand(user_id=user.id))

    verified_user = _make_user(verified=True)
    with pytest.raises(EmailAlreadyVerifiedError):
        await SendEmailVerificationUseCase(
            FakeUserRepo(verified_user), store, sender
        ).execute(SendEmailVerificationCommand(user_id=verified_user.id))


async def test_send_verification_rolls_back_on_sender_failure() -> None:
    user = _make_user(verified=False)
    store = FakeVerificationStore()
    sender = FakeCodeSender(fail=True)
    uc = SendEmailVerificationUseCase(FakeUserRepo(user), store, sender)

    with pytest.raises(EmailVerificationUnavailableError):
        await uc.execute(SendEmailVerificationCommand(user_id=user.id))

    assert len(store.rolled_back) == 1
    assert user.id not in store.codes
    assert user.id not in store.tokens


async def test_confirm_verification_locks_row_and_is_idempotent() -> None:
    user = _make_user(verified=False)
    repo = FakeUserRepo(user)
    store = FakeVerificationStore()
    store.codes[user.id] = "123456"

    uc = ConfirmEmailVerificationUseCase(repo, store)
    await uc.execute(ConfirmEmailVerificationCommand(user_id=user.id, code="123456"))
    assert repo.last_for_update is True
    assert repo.verified_calls == 1
    assert user.email_verified is True

    # 已验证再次确认直接幂等返回 204（不走 store.verify）
    await uc.execute(ConfirmEmailVerificationCommand(user_id=user.id, code="000000"))
    assert store.verify_calls == 1
    assert repo.verified_calls == 1


@pytest.mark.parametrize(
    "bad_result",
    [
        VerificationResult.INVALID,
        VerificationResult.EXPIRED,
        VerificationResult.TOO_MANY,
    ],
)
async def test_confirm_verification_non_ok_raises_unified_error(
    bad_result: VerificationResult,
) -> None:
    user = _make_user(verified=False)
    repo = FakeUserRepo(user)
    store = FakeVerificationStore()
    store.next_result = bad_result

    with pytest.raises(InvalidVerificationCodeError):
        await ConfirmEmailVerificationUseCase(repo, store).execute(
            ConfirmEmailVerificationCommand(user_id=user.id, code="123456")
        )
    assert repo.verified_calls == 0
