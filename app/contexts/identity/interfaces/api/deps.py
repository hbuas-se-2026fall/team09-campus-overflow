from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config.settings import get_settings
from app.contexts.identity.application.confirm_email_verification_use_case import (
    ConfirmEmailVerificationUseCase,
)
from app.contexts.identity.application.login_use_case import LoginUseCase
from app.contexts.identity.application.logout_use_case import LogoutUseCase
from app.contexts.identity.application.ports import (
    ACCESS_TOKEN_TTL,
    LOGIN_FAILURE_THRESHOLD,
    LOGIN_LOCKOUT_WINDOW,
    REFRESH_TOKEN_TTL,
    EmailVerificationStore,
    VerificationCodeSender,
)
from app.contexts.identity.application.refresh_token_use_case import RefreshTokenUseCase
from app.contexts.identity.application.register_use_case import RegisterUseCase
from app.contexts.identity.application.send_email_verification_use_case import (
    SendEmailVerificationUseCase,
)
from app.contexts.identity.application.update_profile_use_case import UpdateProfileUseCase
from app.contexts.identity.domain.repository import UserRepository
from app.contexts.identity.domain.user import Role, User
from app.contexts.identity.infrastructure.email_sender import build_verification_code_sender
from app.contexts.identity.infrastructure.email_verification_store import (
    RedisEmailVerificationStore,
)
from app.contexts.identity.infrastructure.login_attempt_guard import RedisLoginAttemptGuard
from app.contexts.identity.infrastructure.password_hasher import BcryptPasswordHasher
from app.contexts.identity.infrastructure.refresh_store import RedisRefreshTokenStore
from app.contexts.identity.infrastructure.repository import SqlAlchemyUserRepository
from app.contexts.identity.infrastructure.token_service import JwtTokenService
from app.platform.http.deps import SessionDep
from app.shared.redis import get_redis

_bearer = HTTPBearer(auto_error=False)
# 模块级单例：不每请求重建（JWT 校验无请求级状态）
token_service = JwtTokenService(
    get_settings().jwt_secret, ACCESS_TOKEN_TTL, REFRESH_TOKEN_TTL
)
refresh_store = RedisRefreshTokenStore()
login_attempt_guard = RedisLoginAttemptGuard(LOGIN_FAILURE_THRESHOLD, LOGIN_LOCKOUT_WINDOW)


def build_register_use_case(users: UserRepository) -> RegisterUseCase:
    """组装注册用例：仓储 + 哈希器依赖注入。"""
    return RegisterUseCase(users, BcryptPasswordHasher())


def build_login_use_case(users: UserRepository) -> LoginUseCase:
    """组装登录用例：仓储 + 哈希器 + 令牌服务 + 刷新存储 + 失败锁定守卫（US-L04）。"""
    return LoginUseCase(
        users,
        BcryptPasswordHasher(),
        token_service,
        refresh_store,
        login_attempt_guard,
    )


def build_refresh_token_use_case(users: UserRepository) -> RefreshTokenUseCase:
    """组装刷新用例：仓储 + 令牌服务 + 刷新存储（US-L02 轮换）。"""
    return RefreshTokenUseCase(users, token_service, refresh_store)


def build_logout_use_case() -> LogoutUseCase:
    """组装登出用例：令牌服务 + 刷新存储（US-L03 幂等吊销）。"""
    return LogoutUseCase(token_service, refresh_store)


def get_email_verification_store() -> EmailVerificationStore:
    return RedisEmailVerificationStore(
        get_settings().email_verify_hmac_secret, get_redis
    )


def get_verification_code_sender() -> VerificationCodeSender:
    return build_verification_code_sender(get_settings())


EmailVerificationStoreDep = Annotated[
    EmailVerificationStore, Depends(get_email_verification_store)
]
VerificationCodeSenderDep = Annotated[
    VerificationCodeSender, Depends(get_verification_code_sender)
]


def build_update_profile_use_case(users: UserRepository) -> UpdateProfileUseCase:
    return UpdateProfileUseCase(users)


def build_send_email_verification_use_case(
    users: UserRepository,
    store: EmailVerificationStore,
    sender: VerificationCodeSender,
) -> SendEmailVerificationUseCase:
    return SendEmailVerificationUseCase(users, store, sender)


def build_confirm_email_verification_use_case(
    users: UserRepository,
    store: EmailVerificationStore,
) -> ConfirmEmailVerificationUseCase:
    return ConfirmEmailVerificationUseCase(users, store)


def get_user_repository(session: SessionDep) -> UserRepository:
    return SqlAlchemyUserRepository(session)


UserRepo = Annotated[UserRepository, Depends(get_user_repository)]


async def get_current_user(
    session: SessionDep,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    """解析 Authorization: Bearer → 校验 Access 令牌 → 查库返回当前用户（2.3）。"""
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未提供认证令牌")
    user_id = token_service.verify_access(credentials.credentials)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "令牌无效或已过期")
    user = await get_user_repository(session).get_by_id(user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    return user


def require_roles(*roles: Role) -> Callable[..., Awaitable[User]]:
    """RBAC 依赖工厂：要求当前用户属于指定角色之一。"""

    async def _checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "权限不足")
        return user

    return _checker


# 公开供给面：下游上下文（如 qa）只经此别名消费当前用户，
# 不直接 import identity.domain（context-map 边界规则 4 的 interfaces 层例外）
CurrentUser = Annotated[User, Depends(get_current_user)]
