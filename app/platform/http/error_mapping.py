"""领域错误映射共享件（platform/http）：handler 工厂 + 校验异常注册。

各上下文仍拥有自己的"异常类 → 状态码"表；本模块只统一 handler 形状，
避免 identity/qa 各抄一份 `_make_handler`（DRY）。

红线：只注册 `DomainValidationError`（ValueError 子类），**绝不注册裸 ValueError**——
否则程序内部 bug 会被误判成 422。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.shared.errors import DomainValidationError

Handler = Callable[[Request, Exception], Awaitable[JSONResponse]]


def make_domain_error_handler(status_code: int) -> Handler:
    """构造"返回 JSONResponse"的领域错误处理器。

    注意：handler 必须【返回】响应对象；在 handler 内 raise HTTPException
    会越过 ExceptionMiddleware，最终变成 500。
    """

    async def handler(_request: Request, exc: Exception) -> JSONResponse:
        # detail 形制与 FastAPI HTTPException 一致，客户端契约不变
        return JSONResponse(status_code=status_code, content={"detail": str(exc)})

    return handler


def register_validation_error_handler(application: FastAPI) -> None:
    """输入校验错误统一 422（Pydantic validator 内的同种子类仍走数组形 422）。"""
    application.add_exception_handler(
        DomainValidationError,
        make_domain_error_handler(status.HTTP_422_UNPROCESSABLE_CONTENT),
    )
