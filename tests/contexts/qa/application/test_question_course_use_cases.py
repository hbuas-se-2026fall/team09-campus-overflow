"""F17 应用层单元测试：课程发问/编辑准入矩阵与课程榜单用例。"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from uuid import UUID, uuid4

import pytest

from app.contexts.qa.application.ask_question_use_case import AskQuestionUseCase
from app.contexts.qa.application.commands import (
    AskQuestionCommand,
    EditQuestionCommand,
)
from app.contexts.qa.application.edit_question_use_case import EditQuestionUseCase
from app.contexts.qa.application.get_course_leaderboard_use_case import (
    GetCourseLeaderboardUseCase,
)
from app.contexts.qa.application.ports import CourseSummary
from app.contexts.qa.application.queries import GetCourseLeaderboardQuery
from app.contexts.qa.domain.errors import (
    CourseEnrollmentRequiredError,
    CourseNotFoundError,
    QuestionClosedError,
)
from app.contexts.qa.domain.question import Question
from app.contexts.qa.domain.repository import (
    CourseLeaderboardEntry,
    QuestionFilter,
    QuestionSort,
)
from app.contexts.qa.domain.tag import Tag
from app.shared.errors import DomainValidationError
from app.shared.sentinel import UNSET


class FakeQuestionRepo:
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
        q = self.items.get(question_id)
        if q is None or (not include_deleted and q.is_deleted):
            return None
        return q

    async def soft_delete(self, question_id: UUID, deleted_at: datetime) -> bool:
        return False

    async def list_related(self, question_id: UUID, limit: int) -> list[Question]:
        return []

    async def list_paginated(
        self,
        page: int,
        page_size: int,
        sort: QuestionSort = QuestionSort.LATEST,
        filters: QuestionFilter | None = None,
    ) -> tuple[list[Question], int]:
        rows = list(self.items.values())
        if filters is not None and filters.course_id is not None:
            rows = [r for r in rows if r.course_id == filters.course_id]
        return rows, len(rows)


class FakeTagCatalogRepo:
    async def get_or_create(self, tag: Tag) -> Tag:
        return Tag(value=tag.value, id=uuid4())

    async def list_all(self) -> list[Tag]:
        return []


class FakeCourseAccessReader:
    def __init__(
        self,
        courses: dict[UUID, CourseSummary],
        enrollments: set[tuple[UUID, UUID]],
    ) -> None:
        self._courses = courses
        self._enrollments = enrollments

    async def get_summary(self, course_id: UUID) -> CourseSummary | None:
        return self._courses.get(course_id)

    async def get_summaries(
        self, course_ids: Iterable[UUID]
    ) -> dict[UUID, CourseSummary]:
        return {cid: self._courses[cid] for cid in course_ids if cid in self._courses}

    async def is_enrolled(self, course_id: UUID, student_id: UUID) -> bool:
        return (course_id, student_id) in self._enrollments


class FakeCourseLeaderboardRepo:
    def __init__(self, entries_by_course: dict[UUID, list[CourseLeaderboardEntry]]) -> None:
        self._entries = entries_by_course

    async def list_top_contributors(
        self, course_id: UUID, *, limit: int
    ) -> list[CourseLeaderboardEntry]:
        return self._entries.get(course_id, [])[:limit]


class TestAskQuestionWithCourse:
    async def test_enrolled_student_and_staff_can_ask_with_course(self) -> None:
        course_id = uuid4()
        student_id = uuid4()
        summary = CourseSummary(
            course_id=course_id,
            code="CS-SE-301",
            name="软件工程",
            semester="2026-Fall",
        )
        reader = FakeCourseAccessReader(
            {course_id: summary},
            {(course_id, student_id)},
        )
        q_repo = FakeQuestionRepo()
        uc = AskQuestionUseCase(q_repo, FakeTagCatalogRepo(), reader)

        q1 = await uc.execute(
            AskQuestionCommand(
                title="领域建模如何区分实体与值对象？",
                body="以软件工程课程中的 CourseCode 为例说明身份标识与不可变性。",
                author_id=student_id,
                course_id=course_id,
                actor_role="student",
            )
        )
        assert q1.course_id == course_id

        for role in ("teacher", "ta", "admin"):
            q_staff = await uc.execute(
                AskQuestionCommand(
                    title=f"{role} 跨课程答疑示例",
                    body="教师、助教与管理员允许跨课程发起讨论。",
                    author_id=uuid4(),
                    course_id=course_id,
                    actor_role=role,
                )
            )
            assert q_staff.course_id == course_id

    async def test_unenrolled_student_rejected_403_and_missing_course_404(self) -> None:
        course_id = uuid4()
        summary = CourseSummary(
            course_id=course_id,
            code="CS-OS-201",
            name="操作系统",
            semester="2026-Fall",
        )
        reader = FakeCourseAccessReader({course_id: summary}, set())
        q_repo = FakeQuestionRepo()
        uc = AskQuestionUseCase(q_repo, FakeTagCatalogRepo(), reader)

        with pytest.raises(CourseEnrollmentRequiredError):
            await uc.execute(
                AskQuestionCommand(
                    title="未选课学生提问尝试",
                    body="应当在应用层准入策略处被拦截。",
                    author_id=uuid4(),
                    course_id=course_id,
                    actor_role="student",
                )
            )

        with pytest.raises(CourseNotFoundError):
            await uc.execute(
                AskQuestionCommand(
                    title="不存在课程提问尝试",
                    body="应当抛出 CourseNotFoundError。",
                    author_id=uuid4(),
                    course_id=uuid4(),
                    actor_role="teacher",
                )
            )

        assert q_repo.items == {}


class TestEditQuestionWithCourse:
    async def test_edit_course_association_matrix(self) -> None:
        c1, c2 = uuid4(), uuid4()
        student_id = uuid4()
        courses = {
            c1: CourseSummary(c1, "CS-SE-301", "软件工程", "2026-Fall"),
            c2: CourseSummary(c2, "CS-DB-202", "数据库系统原理", "2026-Fall"),
        }
        reader = FakeCourseAccessReader(courses, {(c1, student_id)})
        q_repo = FakeQuestionRepo()
        ask_uc = AskQuestionUseCase(q_repo, FakeTagCatalogRepo(), reader)
        edit_uc = EditQuestionUseCase(q_repo, reader)

        q = await ask_uc.execute(
            AskQuestionCommand(
                title="原标题",
                body="原正文",
                author_id=student_id,
                course_id=c1,
                actor_role="student",
            )
        )

        # UNSET 保留原 course_id
        await edit_uc.execute(
            EditQuestionCommand(
                question_id=q.id,
                actor_id=student_id,
                title="新标题",
                body=None,
                course_id=UNSET,
                actor_role="student",
            )
        )
        assert q_repo.items[q.id].course_id == c1

        # 未选 c2 学生改绑 c2 → 403
        with pytest.raises(CourseEnrollmentRequiredError):
            await edit_uc.execute(
                EditQuestionCommand(
                    question_id=q.id,
                    actor_id=student_id,
                    title=None,
                    body=None,
                    course_id=c2,
                    actor_role="student",
                )
            )
        assert q_repo.items[q.id].course_id == c1

        # 改绑不存在课程 → 404
        with pytest.raises(CourseNotFoundError):
            await edit_uc.execute(
                EditQuestionCommand(
                    question_id=q.id,
                    actor_id=student_id,
                    title=None,
                    body=None,
                    course_id=uuid4(),
                    actor_role="teacher",
                )
            )

        # 传 None 解绑
        await edit_uc.execute(
            EditQuestionCommand(
                question_id=q.id,
                actor_id=student_id,
                title=None,
                body=None,
                course_id=None,
                actor_role="student",
            )
        )
        assert q_repo.items[q.id].course_id is None

        # 已关闭问题改课程仍 409（先于课程准入检查）
        q_repo.items[q.id].close()
        with pytest.raises(QuestionClosedError):
            await edit_uc.execute(
                EditQuestionCommand(
                    question_id=q.id,
                    actor_id=student_id,
                    title=None,
                    body=None,
                    course_id=c1,
                    actor_role="student",
                )
            )


class TestGetCourseLeaderboardUseCase:
    async def test_returns_view_and_guards_bounds_and_missing_course(self) -> None:
        cid = uuid4()
        u1 = uuid4()
        summary = CourseSummary(cid, "CS-SE-301", "软件工程", "2026-Fall")
        reader = FakeCourseAccessReader({cid: summary}, set())
        entry = CourseLeaderboardEntry(
            user_id=u1,
            accepted_count=2,
            net_votes=10,
            answer_count=3,
            rank=1,
        )
        lb_repo = FakeCourseLeaderboardRepo({cid: [entry]})
        uc = GetCourseLeaderboardUseCase(reader, lb_repo)

        view = await uc.execute(GetCourseLeaderboardQuery(course_id=cid, limit=10))
        assert view.course_code == "CS-SE-301"
        assert view.course_name == "软件工程"
        assert view.entries == [entry]

        with pytest.raises(CourseNotFoundError):
            await uc.execute(GetCourseLeaderboardQuery(course_id=uuid4(), limit=10))

        for bad_limit in (0, 51):
            with pytest.raises(DomainValidationError):
                await uc.execute(GetCourseLeaderboardQuery(course_id=cid, limit=bad_limit))
