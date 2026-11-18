from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy import update as sql_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.identity.domain.errors import IdentityAlreadyExistsError
from app.contexts.identity.domain.user import Role, User
from app.contexts.identity.domain.value_objects import (
    ClassName,
    College,
    Email,
    Nickname,
    PasswordHash,
    StaffId,
    StudentId,
)
from app.contexts.identity.infrastructure.models import (
    RoleModel,
    StudentModel,
    TeacherModel,
    UserModel,
    UserRoleModel,
)
from app.shared.sentinel import UNSET, UnsetType


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

    async def get_by_id(
        self, user_id: UUID, *, for_update: bool = False
    ) -> User | None:
        stmt = self._user_select().where(UserModel.id == user_id)
        if for_update:
            # PG 外连接禁止对可空侧加锁：必须指定 of=UserModel 只锁主表行，
            # 并用 populate_existing=True 刷新同一 Session 内可能预加载的旧值。
            stmt = stmt.with_for_update(of=UserModel).execution_options(
                populate_existing=True
            )
        row = (await self._session.execute(stmt)).one_or_none()
        return None if row is None else _row_to_domain(row)

    async def add(self, user: User) -> None:
        self._session.add(
            UserModel(
                id=user.id,
                email=user.email.value,
                password_hash=user.password_hash.value,
                nickname=user.nickname.value if user.nickname is not None else None,
                college=user.college.value if user.college is not None else None,
                class_name=user.class_name.value if user.class_name is not None else None,
                email_verified=user.email_verified,
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

    async def update_profile(
        self,
        user_id: UUID,
        *,
        nickname: Nickname | None | UnsetType = UNSET,
        college: College | None | UnsetType = UNSET,
        class_name: ClassName | None | UnsetType = UNSET,
    ) -> User | None:
        values: dict[str, Any] = {}
        if not isinstance(nickname, UnsetType):
            values["nickname"] = None if nickname is None else nickname.value
        if not isinstance(college, UnsetType):
            values["college"] = None if college is None else college.value
        if not isinstance(class_name, UnsetType):
            values["class_name"] = None if class_name is None else class_name.value

        if values:
            values["updated_at"] = func.now()
            stmt = (
                sql_update(UserModel)
                .where(UserModel.id == user_id)
                .values(**values)
                .execution_options(synchronize_session=False)
            )
            await self._session.execute(stmt)

        refresh_stmt = (
            self._user_select()
            .where(UserModel.id == user_id)
            .execution_options(populate_existing=True)
        )
        row = (await self._session.execute(refresh_stmt)).one_or_none()
        return None if row is None else _row_to_domain(row)

    async def mark_email_verified(self, user_id: UUID) -> None:
        stmt = (
            sql_update(UserModel)
            .where(UserModel.id == user_id)
            .values(email_verified=True, updated_at=func.now())
            .execution_options(synchronize_session=False)
        )
        await self._session.execute(stmt)


def _row_to_domain(row: Any) -> User:
    """行 → 聚合重建（F09/F10：单查询结果纯同步映射，无额外 SQL）。"""
    model, student_id, staff_id, role_name = row
    return User(
        id=model.id,
        role=cast(Role, role_name if role_name is not None else "student"),
        email=Email(model.email),
        password_hash=PasswordHash(model.password_hash),
        student_id=StudentId(student_id) if student_id is not None else None,
        staff_id=StaffId(staff_id) if staff_id is not None else None,
        created_at=model.created_at,
        nickname=Nickname(model.nickname) if model.nickname is not None else None,
        college=College(model.college) if model.college is not None else None,
        class_name=ClassName(model.class_name) if model.class_name is not None else None,
        email_verified=bool(model.email_verified),
    )
