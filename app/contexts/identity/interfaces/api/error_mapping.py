"""identity 领域错误 → HTTP 状态码的唯一映射（interfaces 层）。

与 qa 同构：注册按 MRO 查找，子类（409/401/423）优先于基类（422）。
handler 必须返回响应对象——在 handler 内 raise HTTPException 会越过
ExceptionMiddleware 变成 500。
"""

from __future__ import annotations

from fastapi import FastAPI, status

from app.contexts.identity.domain.errors import (
    AccountLockedError,
    EmailAlreadyExistsError,
    EmailAlreadyVerifiedError,
    EmailVerificationUnavailableError,
    IdentityAlreadyExistsError,
    IdentityDomainError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    InvalidVerificationCodeError,
    SelfRoleChangeError,
    UserNotFoundError,
    VerificationCooldownError,
)
from app.platform.http.error_mapping import make_domain_error_handler

IDENTITY_ERROR_STATUS: dict[type[Exception], int] = {
    EmailAlreadyExistsError: status.HTTP_409_CONFLICT,
    IdentityAlreadyExistsError: status.HTTP_409_CONFLICT,
    EmailAlreadyVerifiedError: status.HTTP_409_CONFLICT,
    SelfRoleChangeError: status.HTTP_409_CONFLICT,
    UserNotFoundError: status.HTTP_404_NOT_FOUND,
    InvalidCredentialsError: status.HTTP_401_UNAUTHORIZED,
    InvalidRefreshTokenError: status.HTTP_401_UNAUTHORIZED,
    AccountLockedError: status.HTTP_423_LOCKED,
    VerificationCooldownError: status.HTTP_429_TOO_MANY_REQUESTS,
    InvalidVerificationCodeError: status.HTTP_400_BAD_REQUEST,
    EmailVerificationUnavailableError: status.HTTP_503_SERVICE_UNAVAILABLE,
    # 其余 IdentityDomainError 子类（弱密码/缺身份/未知角色）：422
    IdentityDomainError: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def register_identity_error_handlers(application: FastAPI) -> None:
    for exc_type, status_code in IDENTITY_ERROR_STATUS.items():
        application.add_exception_handler(exc_type, make_domain_error_handler(status_code))
