"""course 接口层单元测试（dependency_overrides，不连库，进 CI）。"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

from app.contexts.course.domain.course import Course
from app.contexts.course.domain.enrollment import Enrollment
from app.contexts.course.domain.errors import (
    AlreadyEnrolledError,
    CourseCodeAlreadyExistsError,
    CourseNotFoundError,
)
from app.contexts.course.domain.value_objects import Semester
from app.contexts.course.interfaces.api.deps import (
    get_course_repository,
    get_enrollment_repository,
)
from app.contexts.identity.application.ports import UserSummary
from app.contexts.identity.domain.user import Role, User
from app.contexts.identity.domain.value_objects import (
    Email,
    Nickname,
    PasswordHash,
    StaffId,
    StudentId,
)
from app.contexts.identity.interfaces.api.deps import (
    get_current_user,
    get_user_summary_reader,
)
from app.main import create_app


def _user(role: Role, *, nickname: str | None = None) -> User:
    return User(
        id=uuid4(),
        role=role,
        email=Email(f"{uuid4().hex[:8]}@campus.edu.cn"),
        password_hash=PasswordHash("$2b$12$abcdefghijklmnopqrstuv"),
        student_id=StudentId("2025010101") if role in ("student", "ta") else None,
        staff_id=StaffId("T10086") if role in ("teacher", "admin") else None,
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
        nickname=Nickname(nickname) if nickname else None,
    )


class _FakeCourseRepo:
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
        offset = (page - 1) * page_size
        return rows[offset : offset + page_size], len(rows)


class _FakeEnrollmentRepo:
    def __init__(self, courses: _FakeCourseRepo) -> None:
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
        offset = (page - 1) * page_size
        return rows[offset : offset + page_size], len(rows)


class _FakeSummaryReader:
    def __init__(self, users: list[User]) -> None:
        self._summaries = {
            u.id: UserSummary(user_id=u.id, display_name=u.display_name, role=u.role)
            for u in users
        }

    async def get_summaries(self, user_ids: Iterable[UUID]) -> dict[UUID, UserSummary]:
        return {
            uid: self._summaries[uid]
            for uid in user_ids
            if uid in self._summaries
        }


@pytest.mark.parametrize("role", ["student", "ta"])
async def test_create_course_rejects_student_and_ta_with_403(role: Role) -> None:
    actor = _user(role)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: actor
    app.dependency_overrides[get_course_repository] = _FakeCourseRepo
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(
            "/api/v1/courses",
            json={"code": "CS-SE-301", "name": "软件工程", "semester": "2026-Fall"},
        )
    assert resp.status_code == 403


@pytest.mark.parametrize("role", ["teacher", "ta", "admin"])
async def test_enroll_rejects_non_student_with_403(role: Role) -> None:
    actor = _user(role)
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: actor
    app.dependency_overrides[get_course_repository] = _FakeCourseRepo
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(f"/api/v1/courses/{uuid4()}/enroll")
    assert resp.status_code == 403


async def test_list_course_students_rejects_student_with_403() -> None:
    student = _user("student")
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: student
    app.dependency_overrides[get_course_repository] = _FakeCourseRepo
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get(f"/api/v1/courses/{uuid4()}/students")
    assert resp.status_code == 403


async def test_course_routes_happy_path_errors_and_minimal_disclosure() -> None:
    teacher = _user("teacher", nickname="张老师")
    student = _user("student", nickname="李同学")
    ta = _user("ta", nickname="王助教")
    courses = _FakeCourseRepo()
    enrollments = _FakeEnrollmentRepo(courses)
    summary_reader = _FakeSummaryReader([teacher, student, ta])

    current_actor: list[User] = [teacher]
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: current_actor[0]
    app.dependency_overrides[get_course_repository] = lambda: courses
    app.dependency_overrides[get_enrollment_repository] = lambda: enrollments
    app.dependency_overrides[get_user_summary_reader] = lambda: summary_reader

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # extra=forbid -> 422
        extra_resp = await client.post(
            "/api/v1/courses",
            json={
                "code": "CS-SE-301",
                "name": "软件工程",
                "semester": "2026-Fall",
                "extra": "bad",
            },
        )
        assert extra_resp.status_code == 422

        # 422 unsafe chars
        bad_resp = await client.post(
            "/api/v1/courses",
            json={"code": "CS-SE-301", "name": "软件\x00工程", "semester": "2026-Fall"},
        )
        assert bad_resp.status_code == 422

        # 201 create
        created = await client.post(
            "/api/v1/courses",
            json={"code": "cs-se-301", "name": "软件工程", "semester": "2026-Fall"},
        )
        assert created.status_code == 201
        course_data = created.json()
        assert course_data["code"] == "CS-SE-301"
        assert course_data["teacher_name"] == "张老师"
        course_id = course_data["id"]

        # 409 duplicate code (case-insensitive)
        dup = await client.post(
            "/api/v1/courses",
            json={"code": "CS-SE-301", "name": "软件工程", "semester": "2026-Fall"},
        )
        assert dup.status_code == 409

        # GET /courses public + semester filter
        listed = await client.get("/api/v1/courses", params={"semester": "2026-Fall"})
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        assert listed.json()["items"][0]["teacher_name"] == "张老师"

        # Student enrolls -> 201, duplicate -> 409, missing -> 404
        current_actor[0] = student
        enrolled = await client.post(f"/api/v1/courses/{course_id}/enroll")
        assert enrolled.status_code == 201
        assert enrolled.json()["student_name"] == "李同学"

        dup_enroll = await client.post(f"/api/v1/courses/{course_id}/enroll")
        assert dup_enroll.status_code == 409

        missing_enroll = await client.post(f"/api/v1/courses/{uuid4()}/enroll")
        assert missing_enroll.status_code == 404

        # TA lists students -> 200, minimal disclosure
        current_actor[0] = ta
        students_resp = await client.get(f"/api/v1/courses/{course_id}/students")
        assert students_resp.status_code == 200
        payload = students_resp.json()
        assert payload["total"] == 1
        item = payload["items"][0]
        assert set(item.keys()) == {"student_id", "student_name", "enrolled_at"}
        assert item["student_name"] == "李同学"

        # Missing course students -> 404
        missing_students = await client.get(f"/api/v1/courses/{uuid4()}/students")
        assert missing_students.status_code == 404
