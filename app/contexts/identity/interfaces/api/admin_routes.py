"""管理员用户管理路由（F15）：用户列表 + 角色变更（仅 admin 可调）。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Query

from app.contexts.identity.application.commands import UpdateUserRoleCommand
from app.contexts.identity.application.queries import ListUsersQuery
from app.contexts.identity.domain.user import Role, User
from app.contexts.identity.interfaces.api.deps import (
    AdminUser,
    UserRepo,
    build_list_users_use_case,
    build_update_user_role_use_case,
)
from app.contexts.identity.interfaces.api.schemas import (
    AdminUserItem,
    AdminUserListResponse,
    UpdateUserRoleRequest,
)

admin_router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def _admin_user_item(user: User) -> AdminUserItem:
    """管理员视图白名单装配（绝不包含 password_hash）。"""
    return AdminUserItem(
        id=user.id,
        role=user.role,
        email=user.email.value,
        student_id=user.student_id.value if user.student_id is not None else None,
        staff_id=user.staff_id.value if user.staff_id is not None else None,
        display_name=user.display_name,
        nickname=user.nickname.value if user.nickname is not None else None,
        college=user.college.value if user.college is not None else None,
        class_name=user.class_name.value if user.class_name is not None else None,
        email_verified=user.email_verified,
        created_at=user.created_at,
    )


@admin_router.get(
    "/users",
    response_model=AdminUserListResponse,
    summary="管理员分页查询用户列表（仅 admin；支持按角色筛选）",
)
async def list_admin_users(
    _admin: AdminUser,
    users: UserRepo,
    page: int = Query(default=1, ge=1, description="页码，从 1 起"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数，上限 100"),
    role: Role | None = Query(
        default=None, description="按角色筛选：student / teacher / ta / admin"
    ),
) -> AdminUserListResponse:
    result = await build_list_users_use_case(users).execute(
        ListUsersQuery(page=page, page_size=page_size, role=role)
    )
    return AdminUserListResponse(
        items=[_admin_user_item(user) for user in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )


@admin_router.patch(
    "/users/{user_id}/role",
    response_model=AdminUserItem,
    summary="管理员变更用户角色（仅 admin；禁止修改本人角色 409）",
)
async def update_user_role(
    user_id: UUID,
    payload: UpdateUserRoleRequest,
    admin: AdminUser,
    users: UserRepo,
) -> AdminUserItem:
    updated = await build_update_user_role_use_case(users).execute(
        UpdateUserRoleCommand(
            actor_id=admin.id,
            target_user_id=user_id,
            new_role=payload.role,
        )
    )
    return _admin_user_item(updated)
