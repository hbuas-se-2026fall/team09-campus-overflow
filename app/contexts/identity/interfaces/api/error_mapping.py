"""identity 领域错误 → HTTP 状态码的唯一映射（interfaces 层）。

与 qa 同构：注册按 MRO 查找，子类（409/401/423）优先于基类（422）。
handler 必须返回响应对象——在 handler 内 raise HTTPException 会越过
ExceptionMiddleware 变成 500。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.contexts.identity.domain.errors import (
    AccountLockedError,
    EmailAlreadyExistsError,
    IdentityAlreadyExistsError,
    IdentityDomainError,
    InvalidCredentialsError,
)

IDENTITY_ERROR_STATUS: dict[type[Exception], int] = {
    EmailAlreadyExistsError: status.HTTP_409_CONFLICT,
    IdentityAlreadyExistsError: status.HTTP_409_CONFLICT,
    InvalidCredentialsError: status.HTTP_401_UNAUTHORIZED,
    AccountLockedError: status.HTTP_423_LOCKED,
    # 其余 IdentityDomainError 子类（弱密码/缺身份/未知角色）：422
    IdentityDomainError: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def _make_handler(status_code: int) -> Callable[[Request, Exception], Awaitable[JSONResponse]]:
    async def handler(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})

    return handler


def register_identity_error_handlers(application: FastAPI) -> None:
    for exc_type, status_code in IDENTITY_ERROR_STATUS.items():
        application.add_exception_handler(exc_type, _make_handler(status_code))
