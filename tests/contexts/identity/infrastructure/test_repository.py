"""UserRepository 集成测试：需要本地 PostgreSQL（docker compose up -d）。"""

import uuid
from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy import delete, event

from app.contexts.identity.application.commands import RegisterCommand
from app.contexts.identity.application.register_use_case import RegisterUseCase
from app.contexts.identity.domain.errors import EmailAlreadyExistsError, IdentityAlreadyExistsError
from app.contexts.identity.domain.user import User
from app.contexts.identity.infrastructure.models import UserModel, UserRoleModel
from app.contexts.identity.infrastructure.password_hasher import BcryptPasswordHasher
from app.contexts.identity.infrastructure.repository import SqlAlchemyUserRepository
from app.shared.engine import engine, session_factory

pytestmark = pytest.mark.integration


def _unique_email() -> str:
    return f"{uuid.uuid4()}@stu.edu.cn"


def _unique_student_id() -> str:
    return str(uuid.uuid4().int)[:10]


async def test_register_student_persists_and_roundtrips() -> None:
    email = _unique_email()
    student_id = _unique_student_id()
    async with session_factory() as session:
        use_case = RegisterUseCase(SqlAlchemyUserRepository(session), BcryptPasswordHasher())
        user = await use_case.execute(
            RegisterCommand(
                role="student", email=email, password="Passw0rd8", student_id=student_id
            )
        )
        await session.commit()

        repo = SqlAlchemyUserRepository(session)
        fetched = await repo.get_by_email(email)
        assert fetched is not None and fetched.id == user.id
        assert fetched.password_hash.value.startswith("$2b$")  # 库里是哈希非明文

        by_student = await repo.get_by_student_id(student_id)
        assert by_student is not None and by_student.id == user.id

        assert await repo.get_by_email(f"missing-{uuid.uuid4()}@stu.edu.cn") is None


async def test_duplicate_email_rejected_in_db() -> None:
    email = _unique_email()
    async with session_factory() as session:
        use_case = RegisterUseCase(SqlAlchemyUserRepository(session), BcryptPasswordHasher())
        await use_case.execute(
            RegisterCommand(
                role="student",
                email=email,
                password="Passw0rd8",
                student_id=_unique_student_id(),
            )
        )
        await session.commit()

    async with session_factory() as session:
        use_case = RegisterUseCase(SqlAlchemyUserRepository(session), BcryptPasswordHasher())
        with pytest.raises(EmailAlreadyExistsError):
            await use_case.execute(
                RegisterCommand(
                    role="student",
                    email=email,
                    password="Passw0rd8",
                    student_id=_unique_student_id(),
                )
            )


async def test_duplicate_student_id_rejected_in_db() -> None:
    student_id = _unique_student_id()
    async with session_factory() as session:
        use_case = RegisterUseCase(SqlAlchemyUserRepository(session), BcryptPasswordHasher())
        await use_case.execute(
            RegisterCommand(
                role="student",
                email=_unique_email(),
                password="Passw0rd8",
                student_id=student_id,
            )
        )
        await session.commit()

    async with session_factory() as session:
        use_case = RegisterUseCase(SqlAlchemyUserRepository(session), BcryptPasswordHasher())
        with pytest.raises(IdentityAlreadyExistsError):
            await use_case.execute(
                RegisterCommand(
                    role="student",
                    email=_unique_email(),
                    password="Passw0rd8",
                    student_id=student_id,
                )
            )


async def test_register_teacher_persists() -> None:
    email = _unique_email()
    staff_id = f"T{uuid.uuid4().int % 10_000 + 1_000}"
    async with session_factory() as session:
        use_case = RegisterUseCase(SqlAlchemyUserRepository(session), BcryptPasswordHasher())
        user = await use_case.execute(
            RegisterCommand(role="teacher", email=email, password="Passw0rd8", staff_id=staff_id)
        )
        await session.commit()

        repo = SqlAlchemyUserRepository(session)
        fetched = await repo.get_by_staff_id(staff_id)
        assert fetched is not None and fetched.id == user.id
        assert fetched.role == "teacher"


async def _assert_single_user_select(
    call: Callable[[SqlAlchemyUserRepository], Awaitable[User | None]],
) -> None:
    statements: list[str] = []

    def _before_cursor_execute(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        normalized = statement.upper()
        if normalized.lstrip().startswith("SELECT") and "FROM USERS" in normalized:
            statements.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", _before_cursor_execute)
    try:
        async with session_factory() as session:
            user = await call(SqlAlchemyUserRepository(session))
            assert user is not None
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", _before_cursor_execute)

    assert len(statements) == 1, statements


async def test_read_methods_issue_single_user_select() -> None:
    """F09：四条读路径各自只发 1 条包含 FROM users 的 SELECT。"""
    student_email = _unique_email()
    student_id = _unique_student_id()
    teacher_email = _unique_email()
    staff_id = f"T{uuid.uuid4().int % 10_000 + 1_000}"

    async with session_factory() as session:
        use_case = RegisterUseCase(SqlAlchemyUserRepository(session), BcryptPasswordHasher())
        student = await use_case.execute(
            RegisterCommand(
                role="student",
                email=student_email,
                password="Passw0rd8",
                student_id=student_id,
            )
        )
        await use_case.execute(
            RegisterCommand(
                role="teacher",
                email=teacher_email,
                password="Passw0rd8",
                staff_id=staff_id,
            )
        )
        await session.commit()

    await _assert_single_user_select(lambda repo: repo.get_by_email(student_email))
    await _assert_single_user_select(lambda repo: repo.get_by_student_id(student_id))
    await _assert_single_user_select(lambda repo: repo.get_by_staff_id(staff_id))
    await _assert_single_user_select(lambda repo: repo.get_by_id(student.id))


async def test_missing_user_role_row_falls_back_to_student() -> None:
    """F09 D1：保留无角色行回退 student 的既有行为。"""
    email = _unique_email()
    student_id = _unique_student_id()
    async with session_factory() as session:
        use_case = RegisterUseCase(SqlAlchemyUserRepository(session), BcryptPasswordHasher())
        user = await use_case.execute(
            RegisterCommand(
                role="student", email=email, password="Passw0rd8", student_id=student_id
            )
        )
        await session.flush()
        await session.execute(delete(UserRoleModel).where(UserRoleModel.user_id == user.id))
        await session.commit()

    try:
        async with session_factory() as session:
            fetched = await SqlAlchemyUserRepository(session).get_by_id(user.id)
            assert fetched is not None
            assert fetched.role == "student"
    finally:
        # 清理本用例故意制造的“无角色用户”，避免污染后续集成测试与库级数据完整性。
        async with session_factory() as session:
            await session.execute(delete(UserModel).where(UserModel.id == user.id))
            await session.commit()
