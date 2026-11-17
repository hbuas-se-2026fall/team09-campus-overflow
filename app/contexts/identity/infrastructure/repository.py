from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.identity.domain.errors import IdentityAlreadyExistsError
from app.contexts.identity.domain.user import Role, User
from app.contexts.identity.domain.value_objects import Email, PasswordHash, StaffId, StudentId
from app.contexts.identity.infrastructure.models import (
    RoleModel,
    StudentModel,
    TeacherModel,
    UserModel,
    UserRoleModel,
)


class SqlAlchemyUserRepository:
    """UserRepository 端口的 SQLAlchemy 实现。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def _user_select(self) -> Select[Any]:
        """四条读路径共用的单次查询骨架（F09）。

        Student/Teacher 是一对一扩展；UserRole/Role 当前业务不变式为单角色，
        因此正常情况下每个用户恰好一行。多角色脏数据会让 one_or_none()
        抛 MultipleResultsFound，按 F09 D1 视为数据完整性故障（500 + 服务端日志），
        不在本特性提前改 User.role 为集合。
        """
        return (
            select(
                UserModel,
                StudentModel.student_id,
                TeacherModel.staff_id,
                RoleModel.name,
            )
            .outerjoin(StudentModel, StudentModel.user_id == UserModel.id)
            .outerjoin(TeacherModel, TeacherModel.user_id == UserModel.id)
            .outerjoin(UserRoleModel, UserRoleModel.user_id == UserModel.id)
            .outerjoin(RoleModel, RoleModel.id == UserRoleModel.role_id)
        )

    async def get_by_email(self, email: str) -> User | None:
        row = (
            await self._session.execute(
                self._user_select().where(UserModel.email == email)
            )
        ).one_or_none()
        return None if row is None else _row_to_domain(row)

    async def get_by_student_id(self, student_id: str) -> User | None:
        row = (
            await self._session.execute(
                self._user_select().where(StudentModel.student_id == student_id)
            )
        ).one_or_none()
        return None if row is None else _row_to_domain(row)

    async def get_by_staff_id(self, staff_id: str) -> User | None:
        row = (
            await self._session.execute(
                self._user_select().where(TeacherModel.staff_id == staff_id)
            )
        ).one_or_none()
        return None if row is None else _row_to_domain(row)

    async def get_by_id(self, user_id: UUID) -> User | None:
        row = (
            await self._session.execute(
                self._user_select().where(UserModel.id == user_id)
            )
        ).one_or_none()
        return None if row is None else _row_to_domain(row)

    async def add(self, user: User) -> None:
        self._session.add(
            UserModel(
                id=user.id,
                email=user.email.value,
                password_hash=user.password_hash.value,
                created_at=user.created_at,
                updated_at=user.created_at,
            )
        )

        try:
            # 注意：本块内任何查询都可能触发 autoflush 提前执行 INSERT（唯一冲突随之处抛出），
            # 故查询与 flush 必须全部纳入 try，否则竞态 IntegrityError 会绕过 409 兜底
            # （第五路 K-01：并发同 email 注册曾漏成 400）。
            role_stmt = select(RoleModel).where(RoleModel.name == user.role)
            role = (await self._session.execute(role_stmt)).scalar_one()
            self._session.add(UserRoleModel(user_id=user.id, role_id=role.id))

            if user.student_id is not None:
                self._session.add(
                    StudentModel(user_id=user.id, student_id=user.student_id.value)
                )
            if user.staff_id is not None:
                self._session.add(
                    TeacherModel(user_id=user.id, staff_id=user.staff_id.value)
                )

            await self._session.flush()
        except IntegrityError as exc:
            # 不回显 exc.orig（含约束名/DB 细节）；详情随异常链入服务端日志
            raise IdentityAlreadyExistsError("注册信息唯一性冲突（并发兜底）") from exc


def _row_to_domain(row: Any) -> User:
    """行 → 聚合重建（F09：单查询结果纯同步映射，无额外 SQL）。"""
    model, student_id, staff_id, role_name = row
    return User(
        id=model.id,
        role=cast(Role, role_name if role_name is not None else "student"),
        email=Email(model.email),
        password_hash=PasswordHash(model.password_hash),
        student_id=StudentId(student_id) if student_id is not None else None,
        staff_id=StaffId(staff_id) if staff_id is not None else None,
        created_at=model.created_at,
    )
