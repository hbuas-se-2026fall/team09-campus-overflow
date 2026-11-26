"""F15 教师认证回答接口单元测试（dependency_overrides，不连库，进 CI）。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx
import pytest

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
from app.contexts.qa.domain.answer import Answer
from app.contexts.qa.domain.comment import Comment, CommentTarget
from app.contexts.qa.domain.question import Question
from app.contexts.qa.domain.repository import QuestionFilter, QuestionSort
from app.contexts.qa.interfaces.api.deps import (
    get_answer_repository,
    get_comment_repository,
    get_notification_writer,
    get_question_repository,
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
        created_at=datetime.now(UTC),
        nickname=Nickname(nickname) if nickname else None,
    )


class _FakeQRepo:
    def __init__(self, q: Question) -> None:
        self._q = q

    async def add(self, question: Question) -> None:
        return None

    async def update(self, question: Question) -> None:
        return None

    async def get_by_id(
        self,
        question_id: UUID,
        *,
        for_update: bool = False,
        include_deleted: bool = False,
    ) -> Question | None:
        return self._q if question_id == self._q.id else None

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
        return [self._q], 1


class _FakeARepo:
    def __init__(self, a: Answer) -> None:
        self._a = a

    async def add(self, answer: Answer) -> None:
        return None

    async def update(self, answer: Answer) -> None:
        return None

    async def update_body(self, answer: Answer) -> None:
        return None

    async def update_verification(self, answer: Answer) -> None:
        self._a = answer

    async def get_by_id(
        self, answer_id: UUID, *, include_deleted: bool = False
    ) -> Answer | None:
        return self._a if answer_id == self._a.id else None

    async def soft_delete(self, answer_id: UUID, deleted_at: datetime) -> bool:
        return False

    async def list_by_question(self, question_id: UUID) -> list[Answer]:
        return [self._a]


class _FakeCRepo:
    def __init__(self, items: list[Comment]) -> None:
        self._items = items

    async def add(self, comment: Comment) -> None:
        return None

    async def get_by_id(self, comment_id: UUID) -> Comment | None:
        return None

    async def list_by_target(
        self, target_type: CommentTarget, target_id: UUID
    ) -> list[Comment]:
        return [
            c
            for c in self._items
            if c.target_type == target_type and c.target_id == target_id
        ]


class _FakeSummaryReader:
    def __init__(self, mapping: dict[UUID, UserSummary]) -> None:
        self._mapping = mapping

    async def get_summaries(self, user_ids: object) -> dict[UUID, UserSummary]:
        ids = list(user_ids)  # type: ignore[arg-type]
        return {uid: self._mapping[uid] for uid in ids if uid in self._mapping}


class _FakeNotifier:
    def __init__(self) -> None:
        self.items: list[dict[str, object]] = []

    async def write(self, **kwargs: object) -> None:
        self.items.append(kwargs)


async def test_verify_and_unverify_routes_rbac_and_response_unit() -> None:
    student = _user("student", nickname="提问学生")
    ta = _user("ta", nickname="张助教")
    question = Question.ask(
        title_value="TCP 拥塞控制中慢启动与拥塞避免阈值如何切换？",
        body_value="当 cwnd 达到 ssthresh 后窗口增长规律有何变化？",
        author_id=student.id,
    )
    answer = Answer.post(
        question_id=question.id,
        author_id=student.id,
        body_value="超过 ssthresh 后进入拥塞避免阶段，每 RTT 线性增加 1 个 MSS。",
    )
    answer.votes_count = 3
    comment = Comment.write(
        target_type=CommentTarget.ANSWER,
        target_id=answer.id,
        author_id=student.id,
        body_value="补充：发生超时重传时 ssthresh 设为 cwnd/2。",
    )

    actor_holder = {"user": student}
    notifier = _FakeNotifier()
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: actor_holder["user"]
    app.dependency_overrides[get_question_repository] = lambda: _FakeQRepo(question)
    app.dependency_overrides[get_answer_repository] = lambda: _FakeARepo(answer)
    app.dependency_overrides[get_comment_repository] = lambda: _FakeCRepo([comment])
    app.dependency_overrides[get_notification_writer] = lambda: notifier
    app.dependency_overrides[get_user_summary_reader] = lambda: _FakeSummaryReader(
        {
            student.id: UserSummary(student.id, student.display_name, "student"),
            ta.id: UserSummary(ta.id, ta.display_name, "ta"),
        }
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 学生无权认证/取消认证 → 403
        r_stu_post = await client.post(f"/api/v1/answers/{answer.id}/verify")
        assert r_stu_post.status_code == 403
        r_stu_del = await client.delete(f"/api/v1/answers/{answer.id}/verify")
        assert r_stu_del.status_code == 403

        # 助教认证 → 200 + 完整 AnswerResponse
        actor_holder["user"] = ta
        r_ok = await client.post(f"/api/v1/answers/{answer.id}/verify")
        assert r_ok.status_code == 200
        data = r_ok.json()
        assert data["is_teacher_verified"] is True
        assert data["verified_by_name"] == "张助教"
        assert data["verified_at"] is not None
        assert data["author_name"] == "提问学生"
        assert data["votes"] == 3
        assert len(data["comments"]) == 1
        assert len(notifier.items) == 1

        # 取消认证 → 204
        r_del = await client.delete(f"/api/v1/answers/{answer.id}/verify")
        assert r_del.status_code == 204
        assert answer.is_teacher_verified is False


@pytest.mark.parametrize("role", ["teacher", "ta", "admin"])
async def test_verify_allows_all_staff_roles_unit(role: Role) -> None:
    actor = _user(role)
    q = Question.ask(
        title_value="操作系统中页表与 TLB 命中率有何关系？",
        body_value="为什么局部性原理能显著提升虚拟地址翻译吞吐？",
        author_id=uuid4(),
    )
    a = Answer.post(
        question_id=q.id,
        author_id=uuid4(),
        body_value="TLB 缓存最近访问页的页表项，命中时无需额外访存页表。",
    )
    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: actor
    app.dependency_overrides[get_question_repository] = lambda: _FakeQRepo(q)
    app.dependency_overrides[get_answer_repository] = lambda: _FakeARepo(a)
    app.dependency_overrides[get_comment_repository] = lambda: _FakeCRepo([])
    app.dependency_overrides[get_notification_writer] = lambda: _FakeNotifier()
    app.dependency_overrides[get_user_summary_reader] = lambda: _FakeSummaryReader(
        {
            actor.id: UserSummary(actor.id, actor.display_name, role),
            a.author_id: UserSummary(a.author_id, "学生#00000001", "student"),
        }
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.post(f"/api/v1/answers/{a.id}/verify")
    assert resp.status_code == 200
    assert resp.json()["is_teacher_verified"] is True
    assert resp.json()["verified_by_name"] == actor.display_name
