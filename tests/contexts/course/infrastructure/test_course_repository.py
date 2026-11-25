"""F16 course 上下文仓储与只读适配器 PG 集成测试。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, event, func, select

from app.contexts.course.domain.course import Course
from app.contexts.course.domain.enrollment import Enrollment
from app.contexts.course.domain.errors import (
    AlreadyEnrolledError,
    CourseCodeAlreadyExistsError,
    CourseNotFoundError,
)
from app.contexts.course.domain.value_objects import Semester
from app.contexts.course.infrastructure.course_access_reader import (
    SqlAlchemyCourseAccessReader,
)
from app.contexts.course.infrastructure.course_repository import (
    SqlAlchemyCourseRepository,
)
from app.contexts.course.infrastructure.enrollment_repository import (
    SqlAlchemyEnrollmentRepository,
)
from app.contexts.course.infrastructure.models import CourseModel
from app.shared.engine import engine, session_factory

pytestmark = pytest.mark.integration


async def test_course_and_enrollment_repositories_and_access_reader() -> None:
    suffix = uuid.uuid4().hex[:6].upper()
    sem_fall = f"2026-Fall-{suffix}"
    sem_spring = f"2026-Spring-{suffix}"
    teacher_id = uuid.uuid4()
    s1 = uuid.uuid4()
    s2 = uuid.uuid4()
    s3 = uuid.uuid4()

    base = datetime(2026, 9, 1, 8, 0, tzinfo=UTC)
    c1 = Course.create(
        code=f"cs-se-{suffix}",
        name="软件工程",
        semester=sem_fall,
        teacher_id=teacher_id,
    )
    c1.created_at = base
    c2 = Course.create(
        code=f"CS-OS-{suffix}",
        name="操作系统",
        semester=sem_fall,
        teacher_id=teacher_id,
    )
    c2.created_at = base + timedelta(minutes=1)
    c3 = Course.create(
        code=f"CS-DB-{suffix}",
        name="数据库系统原理",
        semester=sem_spring,
        teacher_id=teacher_id,
    )
    c3.created_at = base + timedelta(minutes=2)

    created_ids = [c1.id, c2.id, c3.id]
    try:
        async with session_factory() as session:
            course_repo = SqlAlchemyCourseRepository(session)
            await course_repo.add(c1)
            await course_repo.add(c2)
            await course_repo.add(c3)
            await session.commit()

        # 重复课程编号（大小写归一化后相同）→ CourseCodeAlreadyExistsError，不泄露约束细节
        async with session_factory() as session:
            course_repo = SqlAlchemyCourseRepository(session)
            dup = Course.create(
                code=f"CS-SE-{suffix}",
                name="软件工程重复",
                semester=sem_fall,
                teacher_id=teacher_id,
            )
            with pytest.raises(CourseCodeAlreadyExistsError) as exc_info:
                await course_repo.add(dup)
            assert "uq_courses_code" not in str(exc_info.value)
            assert "DETAIL" not in str(exc_info.value)
            await session.rollback()

        # get_by_id + list_paginated + COUNT 对账
        async with session_factory() as session:
            course_repo = SqlAlchemyCourseRepository(session)
            loaded = await course_repo.get_by_id(c1.id)
            assert loaded is not None
            assert loaded.code.value == f"CS-SE-{suffix}"
            assert await course_repo.get_by_id(uuid.uuid4()) is None

            fall_items, fall_total = await course_repo.list_paginated(
                page=1, page_size=1, semester=Semester(sem_fall)
            )
            assert fall_total == 2
            assert [c.id for c in fall_items] == [c2.id]

            db_total = int(
                (
                    await session.execute(select(func.count()).select_from(CourseModel))
                ).scalar_one()
            )
            all_items, reported_total = await course_repo.list_paginated(
                page=1, page_size=10
            )
            assert reported_total == db_total
            assert len(all_items) <= 10

        # EnrollmentRepository：新增、重复 409、缺失课程 404、正序分页
        async with session_factory() as session:
            enroll_repo = SqlAlchemyEnrollmentRepository(session)
            e1 = Enrollment.enroll(course_id=c1.id, student_id=s1)
            e1.enrolled_at = base
            e2 = Enrollment.enroll(course_id=c1.id, student_id=s2)
            e2.enrolled_at = base + timedelta(seconds=10)
            e3 = Enrollment.enroll(course_id=c1.id, student_id=s3)
            e3.enrolled_at = base + timedelta(seconds=20)
            for enrollment in (e1, e2, e3):
                await enroll_repo.add(enrollment)
            await session.commit()

        async with session_factory() as session:
            enroll_repo = SqlAlchemyEnrollmentRepository(session)
            assert await enroll_repo.exists(c1.id, s1) is True
            assert await enroll_repo.exists(c1.id, uuid.uuid4()) is False

            with pytest.raises(AlreadyEnrolledError) as dup_exc:
                await enroll_repo.add(Enrollment.enroll(course_id=c1.id, student_id=s1))
            assert "uq_enrollments_course_student" not in str(dup_exc.value)
            await session.rollback()

        async with session_factory() as session:
            enroll_repo = SqlAlchemyEnrollmentRepository(session)
            with pytest.raises(CourseNotFoundError) as fk_exc:
                await enroll_repo.add(
                    Enrollment.enroll(course_id=uuid.uuid4(), student_id=s1)
                )
            assert "fk_enrollments_course_id" not in str(fk_exc.value)
            await session.rollback()

        async with session_factory() as session:
            enroll_repo = SqlAlchemyEnrollmentRepository(session)
            page1, total_students = await enroll_repo.list_by_course_paginated(
                c1.id, page=1, page_size=2
            )
            assert total_students == 3
            assert [e.student_id for e in page1] == [s1, s2]

        # CourseAccessReader：空集零 SQL + 摘要查询 + is_enrolled
        sql_count = 0

        def _count_sql(*_args: object) -> None:
            nonlocal sql_count
            sql_count += 1

        event.listen(engine.sync_engine, "before_cursor_execute", _count_sql)
        try:
            async with session_factory() as session:
                reader = SqlAlchemyCourseAccessReader(session)
                sql_count = 0
                assert await reader.get_summaries([]) == {}
                assert sql_count == 0

                summary = await reader.get_summary(c1.id)
                assert summary is not None
                assert summary.code == f"CS-SE-{suffix}"
                assert await reader.get_summary(uuid.uuid4()) is None

                summaries = await reader.get_summaries([c1.id, c3.id, uuid.uuid4()])
                assert set(summaries.keys()) == {c1.id, c3.id}
                assert await reader.is_enrolled(c1.id, s2) is True
                assert await reader.is_enrolled(c2.id, s2) is False
        finally:
            event.remove(engine.sync_engine, "before_cursor_execute", _count_sql)
    finally:
        async with session_factory() as session:
            await session.execute(
                delete(CourseModel).where(CourseModel.id.in_(created_ids))
            )
            await session.commit()
