"""公开用户摘要与个人主页读模型适配器（F11）：显式列投影 + 零敏感表连接。"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.identity.application.ports import PublicUserProfile, UserSummary
from app.contexts.identity.domain.user import (
    normalize_public_nickname,
    resolve_display_name,
)
from app.contexts.identity.infrastructure.models import (
    RoleModel,
    UserModel,
    UserRoleModel,
)

logger = logging.getLogger(__name__)

# 多角色脏数据固定优先级裁定（F15 扩展：admin > teacher > ta > student，
# 其余未知角色按 (99, 角色名) 排后）。
_ROLE_PRIORITY: dict[str, int] = {
    "admin": 0,
    "teacher": 1,
    "ta": 2,
    "student": 3,
}


def _resolve_user_role(user_id: UUID, raw_roles: list[str | None]) -> str:
    """将同用户多行角色记录收敛为唯一确定角色；无角色行按 F09 约定回退 student。"""
    roles = [r for r in raw_roles if r is not None]
    if not roles:
        return "student"
    unique_roles = sorted(set(roles), key=lambda r: (_ROLE_PRIORITY.get(r, 99), r))
    if len(unique_roles) > 1:
        logger.warning(
            "用户存在多角色脏数据，按固定优先级取首个角色: user_id=%s roles=%s picked=%s",
            user_id,
            unique_roles,
            unique_roles[0],
        )
    return unique_roles[0]


class SqlAlchemyUserSummaryReader:
    """UserSummaryReader 与 PublicUserProfileReader 的 SQLAlchemy 只读实现。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_summaries(self, user_ids: Iterable[UUID]) -> dict[UUID, UserSummary]:
        unique_ids = list(dict.fromkeys(user_ids))
        if not unique_ids:
            return {}

        stmt = (
            select(UserModel.id, UserModel.nickname, RoleModel.name)
            .outerjoin(UserRoleModel, UserRoleModel.user_id == UserModel.id)
            .outerjoin(RoleModel, RoleModel.id == UserRoleModel.role_id)
            .where(UserModel.id.in_(unique_ids))
            .order_by(UserModel.id, RoleModel.name.asc())
        )
        rows = (await self._session.execute(stmt)).all()

        nicknames: dict[UUID, str | None] = {}
        roles_by_user: dict[UUID, list[str | None]] = defaultdict(list)
        for uid, raw_nickname, role_name in rows:
            nicknames.setdefault(uid, raw_nickname)
            roles_by_user[uid].append(role_name)

        summaries: dict[UUID, UserSummary] = {}
        for uid, raw_roles in roles_by_user.items():
            role = _resolve_user_role(uid, raw_roles)
            summaries[uid] = UserSummary(
                user_id=uid,
                display_name=resolve_display_name(role, uid, nicknames[uid]),
                role=role,
            )
        return summaries

    async def get_public_profile(self, user_id: UUID) -> PublicUserProfile | None:
        stmt = (
            select(
                UserModel.id,
                UserModel.nickname,
                UserModel.college,
                UserModel.class_name,
                RoleModel.name,
            )
            .outerjoin(UserRoleModel, UserRoleModel.user_id == UserModel.id)
            .outerjoin(RoleModel, RoleModel.id == UserRoleModel.role_id)
            .where(UserModel.id == user_id)
            .order_by(RoleModel.name.asc())
        )
        rows = (await self._session.execute(stmt)).all()
        if not rows:
            return None

        _, raw_nickname, college, class_name, _ = rows[0]
        role = _resolve_user_role(user_id, [row[4] for row in rows])
        # 与 display_name 共用清洗口径，防止历史库首尾空白导致两者展示不一致
        nickname = normalize_public_nickname(raw_nickname)
        display_name = resolve_display_name(role, user_id, nickname)
        return PublicUserProfile(
            user_id=user_id,
            role=role,
            display_name=display_name,
            nickname=nickname,
            college=college,
            class_name=class_name,
        )
