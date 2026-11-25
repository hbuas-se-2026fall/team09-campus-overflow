"""F17 问题关联课程与课程榜单接口单元测试（dependency_overrides，不连库，进 CI）。"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx

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
from app.contexts.qa.application.ports import CourseSummary
from app.contexts.qa.domain.answer import Answer
from app.contexts.qa.domain.comment import Comment, CommentTarget
from app.contexts.qa.domain.question import Question
from app.contexts.qa.domain.repository import (
    CourseLeaderboardEntry,
    QuestionFilter,
    QuestionSort,
)
from app.contexts.qa.domain.tag import Tag
from app.contexts.qa.interfaces.api.deps import (
    get_answer_repository,
    get_comment_repository,
    get_course_leaderboard_repository,
    get_qa_course_access_reader,
    get_question_repository,
    get_tag_catalog_repository,
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


class _FakeQRepo:
    def __init__(self) -> None:
        self.items: dict[UUID, Question] = {}

    async def add(self, question: Question) -> None:
        self.items[question.id] = question

    async def update(self, question: Question) -> None:
        self.items[question.id] = question

    async def get_by_id(
        self,
        question_id: UUID,
        *,
        for_update: bool = False,
        include_deleted: bool = False,
    ) -> Question | None:
        return self.items.get(question_id)

    async def soft_delete(self, question_id: UUID, deleted_at: datetime) -> bool:
        return False

    async def list_related(self, question_id: UUID, limit: int) -> list[Question]:
        if question_id not in self.items:
            return []
        return [q for q in self.items.values() if q.id != question_id][:limit]

    async def list_paginated(
        self,
        page: int,
        page_size: int,
        sort: QuestionSort = QuestionSort.LATEST,
        filters: QuestionFilter | None = None,
    ) -> tuple[list[Question], int]:
        rows = list(self.items.values())
        if filters is not None and filters.course_id is not None:
            rows = [q for q in rows if q.course_id == filters.course_id]
        return rows, len(rows)


class _FakeARepo:
    async def list_by_question(self, question_id: UUID) -> list[Answer]:
        return []


class _FakeCRepo:
    async def list_by_target(
        self, target_type: CommentTarget, target_id: UUID
    ) -> list[Comment]:
        return []


class _FakeTagRepo:
    async def get_or_create(self, tag: Tag) -> Tag:
        return Tag(value=tag.value, id=uuid4())

    async def list_all(self) -> list[Tag]:
        return []


class _FakeCourseReader:
    def __init__(
        self,
        courses: dict[UUID, CourseSummary],
        enrollments: set[tuple[UUID, UUID]],
    ) -> None:
        self._courses = courses
        self._enrollments = enrollments
        self.get_summary_calls = 0

    async def get_summary(self, course_id: UUID) -> CourseSummary | None:
        self.get_summary_calls += 1
        return self._courses.get(course_id)

    async def get_summaries(
        self, course_ids: Iterable[UUID]
    ) -> dict[UUID, CourseSummary]:
        return {cid: self._courses[cid] for cid in course_ids if cid in self._courses}

    async def is_enrolled(self, course_id: UUID, student_id: UUID) -> bool:
        return (course_id, student_id) in self._enrollments


class _FakeSummaryReader:
    def __init__(self, users: list[User]) -> None:
        self._map = {
            u.id: UserSummary(user_id=u.id, display_name=u.display_name, role=u.role)
            for u in users
        }

    async def get_summaries(self, user_ids: Iterable[UUID]) -> dict[UUID, UserSummary]:
        return {uid: self._map[uid] for uid in user_ids if uid in self._map}


class _FakeCourseLeaderboardRepo:
    def __init__(self, entries: dict[UUID, list[CourseLeaderboardEntry]]) -> None:
        self._entries = entries

    async def list_top_contributors(
        self, course_id: UUID, *, limit: int
    ) -> list[CourseLeaderboardEntry]:
        return self._entries.get(course_id, [])[:limit]


async def test_question_course_routes_access_hydration_and_leaderboard_unit() -> None:
    enrolled_student = _user("student", nickname="已选课同学")
    unenrolled_student = _user("student", nickname="未选课同学")
    teacher = _user("teacher", nickname="软件工程教师")
    course_id = uuid4()
    summary = CourseSummary(course_id, "CS-SE-301", "软件工程", "2026-Fall")

    q_repo = _FakeQRepo()
    course_reader = _FakeCourseReader({course_id: summary}, {(course_id, enrolled_student.id)})
    lb_repo = _FakeCourseLeaderboardRepo(
        {
            course_id: [
                CourseLeaderboardEntry(
                    user_id=teacher.id,
                    accepted_count=3,
                    net_votes=12,
                    answer_count=4,
                    rank=1,
                )
            ]
        }
    )
    summary_reader = _FakeSummaryReader([enrolled_student, unenrolled_student, teacher])

    current_user: list[User] = [enrolled_student]
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: current_user[0]
    app.dependency_overrides[get_question_repository] = lambda: q_repo
    app.dependency_overrides[get_answer_repository] = _FakeARepo
    app.dependency_overrides[get_comment_repository] = _FakeCRepo
    app.dependency_overrides[get_tag_catalog_repository] = _FakeTagRepo
    app.dependency_overrides[get_qa_course_access_reader] = lambda: course_reader
    app.dependency_overrides[get_user_summary_reader] = lambda: summary_reader
    app.dependency_overrides[get_course_leaderboard_repository] = lambda: lb_repo

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 1. 无 course_id 提问不触发课程查库
        q_no_course = await client.post(
            "/api/v1/questions",
            json={"title": "通用算法问题", "body": "无课程关联，向后兼容。"},
        )
        assert q_no_course.status_code == 201
        assert q_no_course.json()["course_id"] is None
        assert q_no_course.json()["course_name"] is None
        assert course_reader.get_summary_calls == 0

        # 2. 未选课学生提问 → 403；不存在课程 → 404
        current_user[0] = unenrolled_student
        denied = await client.post(
            "/api/v1/questions",
            json={
                "title": "未选课提问",
                "body": "应被 403 拦截。",
                "course_id": str(course_id),
            },
        )
        assert denied.status_code == 403

        missing = await client.post(
            "/api/v1/questions",
            json={
                "title": "缺失课程提问",
                "body": "应被 404 拦截。",
                "course_id": str(uuid4()),
            },
        )
        assert missing.status_code == 404

        # 3. 已选课学生提问 → 201 回填 course_name
        current_user[0] = enrolled_student
        created = await client.post(
            "/api/v1/questions",
            json={
                "title": "如何划分限界上下文？",
                "body": "软件工程课程 DDD 实践讨论。",
                "course_id": str(course_id),
            },
        )
        assert created.status_code == 201
        q_data = created.json()
        assert q_data["course_id"] == str(course_id)
        assert q_data["course_name"] == "软件工程"
        qid = q_data["id"]

        # 4. 列表按 course_id 筛选 + 详情 + 相关问题均带 course_id / course_name
        listed = await client.get("/api/v1/questions", params={"course_id": str(course_id)})
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        assert listed.json()["items"][0]["course_name"] == "软件工程"

        detail = await client.get(f"/api/v1/questions/{qid}")
        assert detail.status_code == 200
        assert detail.json()["course_name"] == "软件工程"

        related = await client.get(f"/api/v1/questions/{qid}/related")
        assert related.status_code == 200
        assert len(related.json()) == 1

        # 5. 编辑问题：空 {} 422；仅改 title 保留 course_id；传 course_id=null 解绑
        empty_patch = await client.patch(f"/api/v1/questions/{qid}", json={})
        assert empty_patch.status_code == 422

        keep_course = await client.patch(
            f"/api/v1/questions/{qid}", json={"title": "如何划分限界上下文（修订）"}
        )
        assert keep_course.status_code == 200
        assert keep_course.json()["course_id"] == str(course_id)

        unbind = await client.patch(
            f"/api/v1/questions/{qid}", json={"course_id": None}
        )
        assert unbind.status_code == 200
        assert unbind.json()["course_id"] is None
        assert unbind.json()["course_name"] is None

        # 6. 课程排行榜：200 + display_name 回填；缺失课程 404；limit 越界 422
        lb_ok = await client.get(f"/api/v1/courses/{course_id}/leaderboard")
        assert lb_ok.status_code == 200
        lb_json = lb_ok.json()
        assert lb_json["course_code"] == "CS-SE-301"
        assert lb_json["entries"][0]["display_name"] == "软件工程教师"
        assert lb_json["entries"][0]["rank"] == 1

        assert (await client.get(f"/api/v1/courses/{uuid4()}/leaderboard")).status_code == 404
        assert (
            await client.get(
                f"/api/v1/courses/{course_id}/leaderboard", params={"limit": 51}
            )
        ).status_code == 422
