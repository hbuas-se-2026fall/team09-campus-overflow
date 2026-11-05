from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status

from app.contexts.identity.application.commands import (
    LoginCommand,
    LogoutCommand,
    RefreshTokenCommand,
    RegisterCommand,
)
from app.contexts.identity.application.ports import ACCESS_TOKEN_TTL
from app.contexts.identity.domain.user import User
from app.contexts.identity.interfaces.api.deps import (
    CurrentUser,
    UserRepo,
    build_login_use_case,
    build_logout_use_case,
    build_refresh_token_use_case,
    build_register_use_case,
)
from app.contexts.identity.interfaces.api.schemas import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    TokenPairResponse,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="注册（学生/教师分流）",
)
async def register(
    payload: RegisterRequest,
    users: UserRepo,
) -> RegisterResponse:
    use_case = build_register_use_case(users)
    command = RegisterCommand(
        role=payload.role,
        email=payload.email,
        password=payload.password,
        student_id=payload.student_id,
        staff_id=payload.staff_id,
    )
    try:
        user = await use_case.execute(command)
    except ValueError as exc:  # 值对象格式校验（学号/工号/邮箱）
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    return _user_response(user)


def _user_response(user: User) -> RegisterResponse:
    """注册/当前用户共用的白名单响应装配（绝不包含密码任何形态）。"""
    return RegisterResponse(
        id=user.id,
        role=user.role,
        email=user.email.value,
        student_id=user.student_id.value if user.student_id is not None else None,
        staff_id=user.staff_id.value if user.staff_id is not None else None,
        created_at=user.created_at,
    )


@router.post(
    "/login",
    response_model=TokenPairResponse,
    summary="登录（学号/工号 + 密码 → JWT 双令牌）",
)
async def login(
    payload: LoginRequest,
    users: UserRepo,
) -> TokenPairResponse:
    use_case = build_login_use_case(users)
    result = await use_case.execute(
        LoginCommand(identifier=payload.identifier, password=payload.password)
    )

    return TokenPairResponse(
        access_token=result.access_token,
        refresh_token=result.refresh_token,
        expires_in=int(ACCESS_TOKEN_TTL.total_seconds()),
    )


@router.post(
    "/refresh",
    response_model=TokenPairResponse,
    summary="刷新令牌（轮换：旧 Refresh 原子消耗，签发新对）",
)
async def refresh(
    payload: RefreshRequest,
    users: UserRepo,
) -> TokenPairResponse:
    pair = await build_refresh_token_use_case(users).execute(
        RefreshTokenCommand(refresh_token=payload.refresh_token)
    )
    return TokenPairResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=int(ACCESS_TOKEN_TTL.total_seconds()),
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="退出登录（吊销 Refresh 令牌，幂等 204）",
)
async def logout(payload: RefreshRequest) -> Response:
    await build_logout_use_case().execute(
        LogoutCommand(refresh_token=payload.refresh_token)
    )
    # 幂等：无效/已吊销令牌同样 204，不暴露令牌状态
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/me",
    response_model=RegisterResponse,
    summary="当前用户信息（受保护：需 Bearer Access 令牌）",
)
async def me(user: CurrentUser) -> RegisterResponse:
    return _user_response(user)
