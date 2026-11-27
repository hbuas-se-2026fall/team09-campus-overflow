"""F18 内容举报与管理员后台接口单元测试（dependency_overrides，不连库，进 CI）。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
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
from app.contexts.qa.domain.answer import Answer
from app.contexts.qa.domain.errors import (
    AcceptedAnswerCannotDeleteError,
    AnswerNotFoundError,
    DuplicatePendingReportError,
    QuestionNotFoundError,
    ReportAlreadyResolvedError,
    ReportNotFoundError,
)
from app.contexts.qa.domain.question import Question
from app.contexts.qa.domain.report import (
    Report,
    ReportAction,
    ReportStatus,
    ReportTargetType,
    ResolutionNote,
)
from app.contexts.qa.domain.repository import (
    QuestionFilter,
    QuestionSort,
    ReportTargetPreview,
)
from app.contexts.qa.interfaces.api.deps import (
    get_answer_repository,
    get_bounty_service,
    get_question_repository,
    get_report_repository,
    get_report_target_preview_reader,
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
    def __init__(self, items: list[Question]) -> None:
        self.items: dict[UUID, Question] = {q.id: q for q in items}

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
        return replace(q)

    async def soft_delete(self, question_id: UUID, deleted_at: datetime) -> bool:
        q = self.items.get(question_id)
        if q is None:
            raise QuestionNotFoundError("问题不存在")
        if q.deleted_at is not None:
            return False
        if q.accepted_answer_id is not None:
            raise AcceptedAnswerCannotDeleteError("该问题已有采纳答案，不可删除")
        q.deleted_at = deleted_at
        return True

    async def list_related(self, question_id: UUID, limit: int) -> list[Question]:
        return []

    async def list_paginated(
        self,
        page: int,
        page_size: int,
        sort: QuestionSort = QuestionSort.LATEST,
        filters: QuestionFilter | None = None,
    ) -> tuple[list[Question], int]:
        return [], 0


class _FakeARepo:
    def __init__(self, items: list[Answer]) -> None:
        self.items: dict[UUID, Answer] = {a.id: a for a in items}

    async def get_by_id(
        self, answer_id: UUID, *, include_deleted: bool = False
    ) -> Answer | None:
        a = self.items.get(answer_id)
        if a is None or (not include_deleted and a.is_deleted):
            return None
        return replace(a)

    async def soft_delete(self, answer_id: UUID, deleted_at: datetime) -> bool:
        a = self.items.get(answer_id)
        if a is None:
            raise AnswerNotFoundError("回答不存在")
        if a.deleted_at is not None:
            return False
        if a.is_accepted:
            raise AcceptedAnswerCannotDeleteError("已采纳的回答不可删除")
        a.deleted_at = deleted_at
        return True


class _FakeReportRepo:
    def __init__(self) -> None:
        self.items: dict[UUID, Report] = {}

    async def add(self, report: Report) -> None:
        for existing in self.items.values():
            if (
                existing.status is ReportStatus.PENDING
                and existing.reporter_id == report.reporter_id
                and existing.target_type is report.target_type
                and existing.target_id == report.target_id
            ):
                raise DuplicatePendingReportError("您已举报过该内容，请等待管理员处理")
        self.items[report.id] = report

    async def get_by_id(self, report_id: UUID) -> Report | None:
        return self.items.get(report_id)

    async def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        status: ReportStatus | None = None,
        target_type: ReportTargetType | None = None,
    ) -> tuple[list[Report], int]:
        rows = [
            r
            for r in self.items.values()
            if (status is None or r.status is status)
            and (target_type is None or r.target_type is target_type)
        ]
        rows.sort(key=lambda r: (r.created_at, r.id), reverse=True)
        offset = (page - 1) * page_size
        return rows[offset : offset + page_size], len(rows)

    async def resolve_pending(
        self,
        *,
        report_id: UUID,
        new_status: ReportStatus,
        action: ReportAction,
        note: ResolutionNote | None,
        resolved_by: UUID,
        resolved_at: datetime,
    ) -> Report:
        r = self.items.get(report_id)
        if r is None:
            raise ReportNotFoundError("举报不存在")
        if r.status is not ReportStatus.PENDING:
            raise ReportAlreadyResolvedError("该举报已被处理")
        r.status = new_status
        r.resolution_action = action
        r.resolution_note = note
        r.resolved_by = resolved_by
        r.resolved_at = resolved_at
        return r


class _FakeSummaryReader:
    def __init__(self, users: list[User]) -> None:
        self._map = {
            u.id: UserSummary(user_id=u.id, display_name=u.display_name, role=u.role)
            for u in users
        }

    async def get_summaries(self, user_ids: Iterable[UUID]) -> dict[UUID, UserSummary]:
        return {uid: self._map[uid] for uid in user_ids if uid in self._map}


class _FakePreviewReader:
    def __init__(self, q_repo: _FakeQRepo, a_repo: _FakeARepo) -> None:
        self._q_repo = q_repo
        self._a_repo = a_repo

    async def get_previews(
        self, targets: Iterable[tuple[ReportTargetType, UUID]]
    ) -> dict[tuple[ReportTargetType, UUID], ReportTargetPreview]:
        out: dict[tuple[ReportTargetType, UUID], ReportTargetPreview] = {}
        for target_type, target_id in targets:
            if target_type is ReportTargetType.QUESTION:
                q = self._q_repo.items.get(target_id)
                if q is not None:
                    out[(target_type, target_id)] = ReportTargetPreview(
                        question_id=q.id,
                        title=q.title.value,
                        body=q.body.value,
                        is_deleted=q.is_deleted,
                    )
            elif target_type is ReportTargetType.ANSWER:
                a = self._a_repo.items.get(target_id)
                if a is not None:
                    q = self._q_repo.items.get(a.question_id)
                    out[(target_type, target_id)] = ReportTargetPreview(
                        question_id=a.question_id,
                        title=q.title.value if q is not None else None,
                        body=a.body.value,
                        is_deleted=a.is_deleted or (q.is_deleted if q is not None else False),
                    )
        return out


async def test_reports_routes_rbac_validation_and_resolution_unit() -> None:
    student = _user("student", nickname="普通学生")
    teacher = _user("teacher", nickname="授课教师")
    ta = _user("ta", nickname="课程助教")
    admin = _user("admin", nickname="系统管理员")

    q = Question.ask(
        title_value="编译原理 LL(1) 文法左递归消除",
        body_value="待审核问题内容。",
        author_id=teacher.id,
    )
    ans = Answer.post(question_id=q.id, body_value="待审核回答内容。", author_id=student.id)

    q_repo = _FakeQRepo([q])
    a_repo = _FakeARepo([ans])
    r_repo = _FakeReportRepo()
    summary_reader = _FakeSummaryReader([student, teacher, ta, admin])
    preview_reader = _FakePreviewReader(q_repo, a_repo)
    current_user: list[User] = [student]

    app = create_app()
    app.dependency_overrides[get_current_user] = lambda: current_user[0]
    app.dependency_overrides[get_question_repository] = lambda: q_repo
    app.dependency_overrides[get_answer_repository] = lambda: a_repo
    app.dependency_overrides[get_report_repository] = lambda: r_repo
    app.dependency_overrides[get_bounty_service] = lambda: None
    app.dependency_overrides[get_user_summary_reader] = lambda: summary_reader
    app.dependency_overrides[get_report_target_preview_reader] = lambda: preview_reader

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        # 1. 非 admin 访问后台端点 → 403
        for non_admin in (student, teacher, ta):
            current_user[0] = non_admin
            assert (await client.get("/api/v1/admin/reports")).status_code == 403
            assert (
                await client.post(
                    f"/api/v1/admin/reports/{uuid4()}/resolve",
                    json={"action": "dismiss"},
                )
            ).status_code == 403

        # 2. comment 目标与 extra=forbid 与不安全字符 → 422
        current_user[0] = student
        assert (
            await client.post(
                "/api/v1/reports",
                json={
                    "target_type": "comment",
                    "target_id": str(uuid4()),
                    "reason": "不支持评论举报",
                },
            )
        ).status_code == 422
        assert (
            await client.post(
                "/api/v1/reports",
                json={
                    "target_type": "question",
                    "target_id": str(q.id),
                    "reason": "多余字段校验",
                    "extra": "bad",
                },
            )
        ).status_code == 422
        assert (
            await client.post(
                "/api/v1/reports",
                json={
                    "target_type": "question",
                    "target_id": str(q.id),
                    "reason": "含控制字符\x00测试",
                },
            )
        ).status_code == 422

        # 3. 提交举报 201；重复待处理 409；回答举报 201
        rep_q = await client.post(
            "/api/v1/reports",
            json={
                "target_type": "question",
                "target_id": str(q.id),
                "reason": "包含无关广告引流信息",
            },
        )
        assert rep_q.status_code == 201
        assert rep_q.json()["reporter_name"] == "普通学生"
        assert rep_q.json()["target_question_id"] == str(q.id)
        assert rep_q.json()["target_title"] == "编译原理 LL(1) 文法左递归消除"
        assert rep_q.json()["target_body"] == "待审核问题内容。"
        assert rep_q.json()["target_is_deleted"] is False
        rep_q_id = rep_q.json()["id"]

        assert (
            await client.post(
                "/api/v1/reports",
                json={
                    "target_type": "question",
                    "target_id": str(q.id),
                    "reason": "重复举报尝试",
                },
            )
        ).status_code == 409

        current_user[0] = ta
        rep_a = await client.post(
            "/api/v1/reports",
            json={
                "target_type": "answer",
                "target_id": str(ans.id),
                "reason": "回答与问题无关",
            },
        )
        assert rep_a.status_code == 201
        assert rep_a.json()["target_question_id"] == str(q.id)
        assert rep_a.json()["target_title"] == "编译原理 LL(1) 文法左递归消除"
        assert rep_a.json()["target_body"] == "待审核回答内容。"
        assert rep_a.json()["target_is_deleted"] is False
        rep_a_id = rep_a.json()["id"]

        # 4. admin 默认 pending 查询 + 处置（close_question 422；dismiss/soft_delete 200）
        current_user[0] = admin
        listed_default = await client.get("/api/v1/admin/reports", params={"page_size": 10})
        assert listed_default.status_code == 200
        assert listed_default.json()["total"] == 2

        listed_q = await client.get(
            "/api/v1/admin/reports", params={"target_type": "question"}
        )
        assert listed_q.status_code == 200
        assert listed_q.json()["total"] == 1

        assert (
            await client.post(
                f"/api/v1/admin/reports/{rep_a_id}/resolve",
                json={"action": "close_question"},
            )
        ).status_code == 422

        resolved_a = await client.post(
            f"/api/v1/admin/reports/{rep_a_id}/resolve",
            json={"action": "soft_delete", "note": "  删除垃圾回答  "},
        )
        assert resolved_a.status_code == 200
        assert resolved_a.json()["status"] == "resolved"
        assert resolved_a.json()["resolved_by_name"] == "系统管理员"
        assert resolved_a.json()["resolution_note"] == "删除垃圾回答"
        assert resolved_a.json()["target_question_id"] == str(q.id)
        assert resolved_a.json()["target_title"] == "编译原理 LL(1) 文法左递归消除"
        assert resolved_a.json()["target_body"] == "待审核回答内容。"
        assert resolved_a.json()["target_is_deleted"] is True

        dismissed_q = await client.post(
            f"/api/v1/admin/reports/{rep_q_id}/resolve",
            json={"action": "dismiss", "note": "  "},
        )
        assert dismissed_q.status_code == 200
        assert dismissed_q.json()["status"] == "dismissed"
        assert dismissed_q.json()["resolution_note"] is None

        # 5. status 默认 pending（此时为 0）、status=all（2）、resolved / dismissed / invalid 422
        assert (await client.get("/api/v1/admin/reports")).json()["total"] == 0
        all_resp = await client.get("/api/v1/admin/reports", params={"status": "all"})
        assert all_resp.status_code == 200
        assert all_resp.json()["total"] == 2
        all_by_id = {item["id"]: item for item in all_resp.json()["items"]}
        assert all_by_id[rep_a_id]["target_question_id"] == str(q.id)
        assert all_by_id[rep_a_id]["target_is_deleted"] is True
        assert all_by_id[rep_q_id]["target_question_id"] == str(q.id)
        assert all_by_id[rep_q_id]["target_is_deleted"] is False
        res_resp = await client.get("/api/v1/admin/reports", params={"status": "resolved"})
        assert res_resp.status_code == 200
        assert [item["id"] for item in res_resp.json()["items"]] == [rep_a_id]
        dis_resp = await client.get("/api/v1/admin/reports", params={"status": "dismissed"})
        assert dis_resp.status_code == 200
        assert [item["id"] for item in dis_resp.json()["items"]] == [rep_q_id]
        assert (
            await client.get("/api/v1/admin/reports", params={"status": "unknown"})
        ).status_code == 422

        # 6. 目标对象缺失时，4 个预览字段安全回退为 None
        q_repo.items.clear()
        a_repo.items.clear()
        missing_resp = await client.get("/api/v1/admin/reports", params={"status": "all"})
        assert missing_resp.status_code == 200
        for item in missing_resp.json()["items"]:
            assert item["target_question_id"] is None
            assert item["target_title"] is None
            assert item["target_body"] is None
            assert item["target_is_deleted"] is None
