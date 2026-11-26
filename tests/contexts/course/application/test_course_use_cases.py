"""course 应用层单元测试（LSP 严格对齐 Fake 仓储）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.contexts.course.application.commands import (
    CreateCourseCommand,
    EnrollCourseCommand,
)
from app.contexts.course.application.create_course_use_case import CreateCourseUseCase
from app.contexts.course.application.enroll_course_use_case import EnrollCourseUseCase
from app.contexts.course.application.list_course_students_use_case import (
    ListCourseStudentsUseCase,
)
from app.contexts.course.application.list_courses_use_case import ListCoursesUseCase
from app.contexts.course.application.queries import (
    ListCoursesQuery,
    ListCourseStudentsQuery,
)
from app.contexts.course.domain.course import Course
from app.contexts.course.domain.enrollment import Enrollment
from app.contexts.course.domain.errors import (
    AlreadyEnrolledError,
    CourseCodeAlreadyExistsError,
    CourseNotFoundError,
)
from app.contexts.course.domain.value_objects import Semester
from app.shared.errors import DomainValidationError


class FakeCourseRepository:
    def __init__(self) -> None:
        self.by_id: dict[UUID, Course] = {}
        self.by_code: dict[str, UUID] = {}

    async def add(self, course: Course) -> None:
        if course.code.value in self.by_code:
            raise CourseCodeAlreadyExistsError("课程编号已存在")
        self.by_id[course.id] = course
        self.by_code[course.code.value] = course.id

    async def get_by_id(self, course_id: UUID) -> Course | None:
        return self.by_id.get(course_id)

    async def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        semester: Semester | None = None,
    ) -> tuple[list[Course], int]:
        rows = list(self.by_id.values())
        if semester is not None:
            rows = [item for item in rows if item.semester.value == semester.value]
        rows.sort(key=lambda item: (item.created_at, item.id), reverse=True)
        total = len(rows)
        offset = (page - 1) * page_size
        return rows[offset : offset + page_size], total


class FakeEnrollmentRepository:
    def __init__(self, courses: FakeCourseRepository) -> None:
        self._courses = courses
        self.items: list[Enrollment] = []
        self._pairs: set[tuple[UUID, UUID]] = set()

    async def add(self, enrollment: Enrollment) -> None:
        if await self._courses.get_by_id(enrollment.course_id) is None:
            raise CourseNotFoundError("课程不存在")
        pair = (enrollment.course_id, enrollment.student_id)
        if pair in self._pairs:
            raise AlreadyEnrolledError("已选修该课程，请勿重复选课")
        self._pairs.add(pair)
        self.items.append(enrollment)

    async def exists(self, course_id: UUID, student_id: UUID) -> bool:
        return (course_id, student_id) in self._pairs

    async def list_by_course_paginated(
        self,
        course_id: UUID,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[Enrollment], int]:
        rows = [item for item in self.items if item.course_id == course_id]
        rows.sort(key=lambda item: (item.enrolled_at, item.id))
        total = len(rows)
        offset = (page - 1) * page_size
        return rows[offset : offset + page_size], total


class TestCreateCourseUseCase:
    async def test_creates_course_with_normalized_code(self) -> None:
        repo = FakeCourseRepository()
        teacher_id = uuid4()
        course = await CreateCourseUseCase(repo).execute(
            CreateCourseCommand(
                actor_id=teacher_id,
                code=" cs-se-301 ",
                name="软件工程",
                semester="2026-Fall",
            )
        )
        assert course.code.value == "CS-SE-301"
        assert course.teacher_id == teacher_id
        assert await repo.get_by_id(course.id) == course

    async def test_duplicate_code_case_insensitive_raises_conflict(self) -> None:
        repo = FakeCourseRepository()
        uc = CreateCourseUseCase(repo)
        await uc.execute(
            CreateCourseCommand(
                actor_id=uuid4(),
                code="CS-SE-301",
                name="软件工程",
                semester="2026-Fall",
            )
        )
        with pytest.raises(CourseCodeAlreadyExistsError):
            await uc.execute(
                CreateCourseCommand(
                    actor_id=uuid4(),
                    code="cs-se-301",
                    name="软件工程（重开）",
                    semester="2026-Fall",
                )
            )


class TestListCoursesUseCase:
    async def test_paginates_filters_semester_and_treats_blank_as_unfiltered(
        self,
    ) -> None:
        repo = FakeCourseRepository()
        base = datetime(2026, 9, 1, tzinfo=UTC)
        c1 = Course.create(
            code="CS-SE-301", name="软件工程", semester="2026-Fall", teacher_id=uuid4()
        )
        c1.created_at = base
        c2 = Course.create(
            code="CS-OS-201", name="操作系统", semester="2026-Fall", teacher_id=uuid4()
        )
        c2.created_at = base + timedelta(minutes=1)
        c3 = Course.create(
            code="CS-DB-202", name="数据库系统原理", semester="2026-Spring", teacher_id=uuid4()
        )
        c3.created_at = base + timedelta(minutes=2)
        for c in (c1, c2, c3):
            await repo.add(c)

        uc = ListCoursesUseCase(repo)
        page1 = await uc.execute(ListCoursesQuery(page=1, page_size=2))
        assert [c.code.value for c in page1.items] == ["CS-DB-202", "CS-OS-201"]
        assert page1.total == 3
        assert page1.total_pages == 2

        blank_semester = await uc.execute(
            ListCoursesQuery(page=1, page_size=10, semester="   ")
        )
        assert blank_semester.total == 3

        fall_only = await uc.execute(
            ListCoursesQuery(page=1, page_size=10, semester=" 2026-Fall ")
        )
        assert [c.code.value for c in fall_only.items] == ["CS-OS-201", "CS-SE-301"]
        assert fall_only.total == 2
        assert fall_only.total_pages == 1

    async def test_empty_repo_returns_zero_total_pages(self) -> None:
        repo = FakeCourseRepository()
        res = await ListCoursesUseCase(repo).execute(ListCoursesQuery(page=1, page_size=20))
        assert res.items == []
        assert res.total == 0
        assert res.total_pages == 0

    async def test_invalid_non_blank_semester_raises_domain_validation_error(
        self,
    ) -> None:
        repo = FakeCourseRepository()
        with pytest.raises(DomainValidationError):
            await ListCoursesUseCase(repo).execute(
                ListCoursesQuery(page=1, page_size=20, semester="X")
            )


class TestEnrollAndListStudentsUseCase:
    async def test_enroll_and_duplicate_conflict_and_missing_course(self) -> None:
        courses = FakeCourseRepository()
        enrollments = FakeEnrollmentRepository(courses)
        course = await CreateCourseUseCase(courses).execute(
            CreateCourseCommand(
                actor_id=uuid4(),
                code="CS-OS-201",
                name="操作系统",
                semester="2026-Fall",
            )
        )
        student_id = uuid4()

        with pytest.raises(CourseNotFoundError):
            await EnrollCourseUseCase(courses, enrollments).execute(
                EnrollCourseCommand(course_id=uuid4(), student_id=student_id)
            )

        enrolled = await EnrollCourseUseCase(courses, enrollments).execute(
            EnrollCourseCommand(course_id=course.id, student_id=student_id)
        )
        assert enrolled.course_id == course.id
        assert enrolled.student_id == student_id
        assert await enrollments.exists(course.id, student_id) is True

        with pytest.raises(AlreadyEnrolledError):
            await EnrollCourseUseCase(courses, enrollments).execute(
                EnrollCourseCommand(course_id=course.id, student_id=student_id)
            )

    async def test_list_students_checks_course_exists_and_paginates(self) -> None:
        courses = FakeCourseRepository()
        enrollments = FakeEnrollmentRepository(courses)
        with pytest.raises(CourseNotFoundError):
            await ListCourseStudentsUseCase(courses, enrollments).execute(
                ListCourseStudentsQuery(course_id=uuid4())
            )

        course = await CreateCourseUseCase(courses).execute(
            CreateCourseCommand(
                actor_id=uuid4(),
                code="CS-DB-202",
                name="数据库系统原理",
                semester="2026-Fall",
            )
        )
        s1, s2, s3 = uuid4(), uuid4(), uuid4()
        base = datetime(2026, 9, 2, tzinfo=UTC)
        for idx, sid in enumerate((s1, s2, s3)):
            e = Enrollment.enroll(course_id=course.id, student_id=sid)
            e.enrolled_at = base + timedelta(seconds=idx)
            await enrollments.add(e)

        res = await ListCourseStudentsUseCase(courses, enrollments).execute(
            ListCourseStudentsQuery(course_id=course.id, page=1, page_size=2)
        )
        assert [item.student_id for item in res.items] == [s1, s2]
        assert res.total == 3
        assert res.total_pages == 2
