"""举报应用用例单元测试（F18，LSP Fake 仓储，覆盖 3×2 全矩阵与悬赏退款）。"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from app.contexts.qa.application.bounty_service import BountyService
from app.contexts.qa.application.commands import (
    CreateReportCommand,
    ResolveReportCommand,
)
from app.contexts.qa.application.create_report_use_case import CreateReportUseCase
from app.contexts.qa.application.list_reports_use_case import ListReportsUseCase
from app.contexts.qa.application.queries import ListReportsQuery
from app.contexts.qa.application.report_resolution_handlers import (
    build_report_resolution_handlers,
)
from app.contexts.qa.application.resolve_report_use_case import ResolveReportUseCase
from app.contexts.qa.domain.answer import Answer
from app.contexts.qa.domain.bounty import Bounty, BountyStatus, PointsEntry
from app.contexts.qa.domain.errors import (
    AcceptedAnswerCannotDeleteError,
    AnswerAlreadyAcceptedError,
    AnswerNotFoundError,
    DuplicatePendingReportError,
    InvalidReportActionError,
    QuestionAlreadyClosedError,
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
from app.contexts.qa.domain.repository import QuestionFilter, QuestionSort
from app.shared.errors import DomainValidationError


class FakeQuestionRepo:
    def __init__(self, items: list[Question] | None = None) -> None:
        self.items: dict[UUID, Question] = {q.id: q for q in (items or [])}

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


class FakeAnswerRepo:
    def __init__(
        self, questions: FakeQuestionRepo, items: list[Answer] | None = None
    ) -> None:
        self._questions = questions
        self.items: dict[UUID, Answer] = {a.id: a for a in (items or [])}

    async def add(self, answer: Answer) -> None:
        self.items[answer.id] = answer

    async def update(self, answer: Answer) -> None:
        self.items[answer.id] = answer

    async def update_body(self, answer: Answer) -> None:
        self.items[answer.id] = answer

    async def update_verification(self, answer: Answer) -> None:
        self.items[answer.id] = answer

    async def get_by_id(
        self, answer_id: UUID, *, include_deleted: bool = False
    ) -> Answer | None:
        a = self.items.get(answer_id)
        if a is None:
            return None
        q = self._questions.items.get(a.question_id)
        if not include_deleted and (a.is_deleted or q is None or q.is_deleted):
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

    async def list_by_question(self, question_id: UUID) -> list[Answer]:
        return []


class FakeReportRepo:
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
        report = self.items.get(report_id)
        if report is None:
            raise ReportNotFoundError("举报不存在")
        if report.status is not ReportStatus.PENDING:
            raise ReportAlreadyResolvedError("该举报已被处理")
        report.status = new_status
        report.resolution_action = action
        report.resolution_note = note
        report.resolved_by = resolved_by
        report.resolved_at = resolved_at
        return report


class FakeBountyRepo:
    def __init__(self, bounties: list[Bounty] | None = None) -> None:
        self._bounties = {b.question_id: b for b in (bounties or [])}

    async def add(self, bounty: Bounty) -> None:
        self._bounties[bounty.question_id] = bounty

    async def get_active(self, question_id: UUID) -> Bounty | None:
        b = self._bounties.get(question_id)
        return b if b is not None and b.status is BountyStatus.OPEN else None

    async def settle(self, question_id: UUID) -> Bounty | None:
        return None

    async def refund(self, question_id: UUID) -> Bounty | None:
        b = self._bounties.get(question_id)
        if b is None or b.status is not BountyStatus.OPEN:
            return None
        updated = replace(b, status=BountyStatus.REFUNDED, settled_at=datetime.now(UTC))
        self._bounties[question_id] = updated
        return updated


class FakePointsRepo:
    def __init__(self) -> None:
        self.balances: dict[UUID, int] = {}
        self.entries: list[PointsEntry] = []

    async def ensure_teacher_account(self, user_id: UUID) -> int:
        return self.balances.setdefault(user_id, 100)

    async def get_balance(self, user_id: UUID) -> int:
        return self.balances.get(user_id, 0)

    async def deduct(self, user_id: UUID, amount: int) -> bool:
        return True

    async def credit(self, user_id: UUID, amount: int) -> None:
        self.balances[user_id] = self.balances.get(user_id, 0) + amount

    async def append(self, user_id: UUID, entry: PointsEntry) -> None:
        self.entries.append(entry)

    async def list_entries(self, user_id: UUID) -> list[PointsEntry]:
        return list(self.entries)


def _make_resolve_uc(
    r_repo: FakeReportRepo,
    q_repo: FakeQuestionRepo,
    a_repo: FakeAnswerRepo,
    bounty_service: BountyService | None = None,
) -> ResolveReportUseCase:
    return ResolveReportUseCase(
        r_repo,
        build_report_resolution_handlers(
            question_repo=q_repo,
            answer_repo=a_repo,
            bounty_service=bounty_service,
        ),
    )


async def _resolve_tx(
    uc: ResolveReportUseCase,
    r_repo: FakeReportRepo,
    cmd: ResolveReportCommand,
) -> Report:
    """模拟数据库事务边界：异常时回滚 FakeReportRepo 内存状态，保持 pending。"""
    snapshot = {rid: replace(r) for rid, r in r_repo.items.items()}
    try:
        return await uc.execute(cmd)
    except Exception:
        r_repo.items = snapshot
        raise


class TestCreateAndListReportsUseCase:
    async def test_create_report_duplicate_pending_and_refile_after_dismiss(
        self,
    ) -> None:
        q = Question.ask(
            title_value="计算机网络 TCP 三次握手状态变迁",
            body_value="包含未核实的营销推广链接。",
            author_id=uuid4(),
        )
        a = Answer.post(question_id=q.id, body_value="广告刷屏内容。", author_id=uuid4())
        q_repo = FakeQuestionRepo([q])
        a_repo = FakeAnswerRepo(q_repo, [a])
        r_repo = FakeReportRepo()
        create_uc = CreateReportUseCase(r_repo, q_repo, a_repo)
        reporter_id = uuid4()

        with pytest.raises(QuestionNotFoundError):
            await create_uc.execute(
                CreateReportCommand(
                    reporter_id=reporter_id,
                    target_type=ReportTargetType.QUESTION,
                    target_id=uuid4(),
                    reason="目标不存在校验",
                )
            )
        with pytest.raises(AnswerNotFoundError):
            await create_uc.execute(
                CreateReportCommand(
                    reporter_id=reporter_id,
                    target_type=ReportTargetType.ANSWER,
                    target_id=uuid4(),
                    reason="回答不存在校验",
                )
            )

        r1 = await create_uc.execute(
            CreateReportCommand(
                reporter_id=reporter_id,
                target_type=ReportTargetType.QUESTION,
                target_id=q.id,
                reason="包含无关广告引流链接",
            )
        )
        with pytest.raises(DuplicatePendingReportError):
            await create_uc.execute(
                CreateReportCommand(
                    reporter_id=reporter_id,
                    target_type=ReportTargetType.QUESTION,
                    target_id=q.id,
                    reason="重复提交待处理举报",
                )
            )

        r2 = await create_uc.execute(
            CreateReportCommand(
                reporter_id=reporter_id,
                target_type=ReportTargetType.ANSWER,
                target_id=a.id,
                reason="回答含广告刷屏",
            )
        )

        # 驳回后允许同一用户再次举报同一目标
        resolve_uc = _make_resolve_uc(r_repo, q_repo, a_repo)
        await resolve_uc.execute(
            ResolveReportCommand(
                report_id=r1.id,
                admin_id=uuid4(),
                action=ReportAction.DISMISS,
                note="核实后暂不违规",
            )
        )
        r3 = await create_uc.execute(
            CreateReportCommand(
                reporter_id=reporter_id,
                target_type=ReportTargetType.QUESTION,
                target_id=q.id,
                reason="再次出现违规外链",
            )
        )
        assert r3.id != r1.id and r2.status is ReportStatus.PENDING

        list_uc = ListReportsUseCase(r_repo)
        res = await list_uc.execute(
            ListReportsQuery(
                page=1,
                page_size=10,
                status=ReportStatus.PENDING,
                target_type=ReportTargetType.QUESTION,
            )
        )
        assert [item.id for item in res.items] == [r3.id]
        assert res.total == 1 and res.total_pages == 1

        with pytest.raises(DomainValidationError):
            await list_uc.execute(ListReportsQuery(page=0, page_size=10))
        with pytest.raises(DomainValidationError):
            await list_uc.execute(ListReportsQuery(page=1, page_size=101))


class TestResolveReportMatrix:
    async def test_question_close_and_soft_delete_refund_bounty_and_protect_invariants(
        self,
    ) -> None:
        teacher_id = uuid4()
        q_open = Question.ask(
            title_value="待关贴悬赏问题", body_value="违规引战内容。", author_id=uuid4()
        )
        q_del = Question.ask(
            title_value="待删除悬赏问题", body_value="广告内容。", author_id=uuid4()
        )
        q_accepted = Question.ask(
            title_value="含采纳答案的问题", body_value="已采纳答案。", author_id=uuid4()
        )
        ans_accepted = Answer.post(
            question_id=q_accepted.id, body_value="最佳回答", author_id=uuid4()
        )
        ans_accepted.accept()
        q_accepted.mark_accepted(ans_accepted.id)

        q_repo = FakeQuestionRepo([q_open, q_del, q_accepted])
        a_repo = FakeAnswerRepo(q_repo, [ans_accepted])
        r_repo = FakeReportRepo()

        bounty_open = Bounty(
            id=uuid4(),
            question_id=q_open.id,
            teacher_id=teacher_id,
            amount=30,
            status=BountyStatus.OPEN,
            created_at=datetime.now(UTC),
            settled_at=None,
        )
        bounty_del = Bounty(
            id=uuid4(),
            question_id=q_del.id,
            teacher_id=teacher_id,
            amount=20,
            status=BountyStatus.OPEN,
            created_at=datetime.now(UTC),
            settled_at=None,
        )
        points_repo = FakePointsRepo()
        bounty_service = BountyService(
            FakeBountyRepo([bounty_open, bounty_del]), points_repo
        )
        create_uc = CreateReportUseCase(r_repo, q_repo, a_repo)
        resolve_uc = _make_resolve_uc(r_repo, q_repo, a_repo, bounty_service)

        rep_open = await create_uc.execute(
            CreateReportCommand(
                reporter_id=uuid4(),
                target_type=ReportTargetType.QUESTION,
                target_id=q_open.id,
                reason="关贴测试理由足够长",
            )
        )
        rep_open_2 = await create_uc.execute(
            CreateReportCommand(
                reporter_id=uuid4(),
                target_type=ReportTargetType.QUESTION,
                target_id=q_open.id,
                reason="第二人举报同一问题",
            )
        )
        rep_del = await create_uc.execute(
            CreateReportCommand(
                reporter_id=uuid4(),
                target_type=ReportTargetType.QUESTION,
                target_id=q_del.id,
                reason="删除测试理由足够长",
            )
        )
        rep_acc_q = await create_uc.execute(
            CreateReportCommand(
                reporter_id=uuid4(),
                target_type=ReportTargetType.QUESTION,
                target_id=q_accepted.id,
                reason="已采纳问题保护测试",
            )
        )
        rep_acc_a = await create_uc.execute(
            CreateReportCommand(
                reporter_id=uuid4(),
                target_type=ReportTargetType.ANSWER,
                target_id=ans_accepted.id,
                reason="已采纳回答保护测试",
            )
        )

        # 1. close_question 退开放悬赏 30，随后重复处置同一举报 409；已关贴再 close_question 409
        resolved_close = await _resolve_tx(
            resolve_uc,
            r_repo,
            ResolveReportCommand(
                report_id=rep_open.id,
                admin_id=uuid4(),
                action=ReportAction.CLOSE_QUESTION,
                note="关闭违规讨论",
            ),
        )
        assert resolved_close.status is ReportStatus.RESOLVED
        assert points_repo.balances[teacher_id] == 30
        with pytest.raises(ReportAlreadyResolvedError):
            await _resolve_tx(
                resolve_uc,
                r_repo,
                ResolveReportCommand(
                    report_id=rep_open.id,
                    admin_id=uuid4(),
                    action=ReportAction.DISMISS,
                ),
            )
        with pytest.raises(QuestionAlreadyClosedError):
            await _resolve_tx(
                resolve_uc,
                r_repo,
                ResolveReportCommand(
                    report_id=rep_open_2.id,
                    admin_id=uuid4(),
                    action=ReportAction.CLOSE_QUESTION,
                ),
            )
        assert r_repo.items[rep_open_2.id].status is ReportStatus.PENDING

        # 2. 已关闭且无采纳问题仍允许管理员软删除
        await _resolve_tx(
            resolve_uc,
            r_repo,
            ResolveReportCommand(
                report_id=rep_open_2.id,
                admin_id=uuid4(),
                action=ReportAction.SOFT_DELETE,
            ),
        )
        assert q_repo.items[q_open.id].is_deleted is True

        # 3. soft_delete 问题退开放悬赏 20（累计 50）
        await _resolve_tx(
            resolve_uc,
            r_repo,
            ResolveReportCommand(
                report_id=rep_del.id,
                admin_id=uuid4(),
                action=ReportAction.SOFT_DELETE,
            ),
        )
        assert q_repo.items[q_del.id].is_deleted is True
        assert points_repo.balances[teacher_id] == 50

        # 4. 含采纳答案的问题：禁 close_question(409) 与 soft_delete(409)
        with pytest.raises(AnswerAlreadyAcceptedError):
            await _resolve_tx(
                resolve_uc,
                r_repo,
                ResolveReportCommand(
                    report_id=rep_acc_q.id,
                    admin_id=uuid4(),
                    action=ReportAction.CLOSE_QUESTION,
                ),
            )
        with pytest.raises(AcceptedAnswerCannotDeleteError):
            await _resolve_tx(
                resolve_uc,
                r_repo,
                ResolveReportCommand(
                    report_id=rep_acc_q.id,
                    admin_id=uuid4(),
                    action=ReportAction.SOFT_DELETE,
                ),
            )

        # 5. 回答举报：禁 close_question(422)；已采纳回答禁 soft_delete(409)；仅允许 dismiss
        with pytest.raises(InvalidReportActionError):
            await _resolve_tx(
                resolve_uc,
                r_repo,
                ResolveReportCommand(
                    report_id=rep_acc_a.id,
                    admin_id=uuid4(),
                    action=ReportAction.CLOSE_QUESTION,
                ),
            )
        with pytest.raises(AcceptedAnswerCannotDeleteError):
            await _resolve_tx(
                resolve_uc,
                r_repo,
                ResolveReportCommand(
                    report_id=rep_acc_a.id,
                    admin_id=uuid4(),
                    action=ReportAction.SOFT_DELETE,
                ),
            )
        dismissed = await _resolve_tx(
            resolve_uc,
            r_repo,
            ResolveReportCommand(
                report_id=rep_acc_a.id,
                admin_id=uuid4(),
                action=ReportAction.DISMISS,
            ),
        )
        assert dismissed.status is ReportStatus.DISMISSED

        with pytest.raises(ReportNotFoundError):
            await _resolve_tx(
                resolve_uc,
                r_repo,
                ResolveReportCommand(
                    report_id=uuid4(),
                    admin_id=uuid4(),
                    action=ReportAction.DISMISS,
                ),
            )

    async def test_dismiss_allows_already_deleted_target_and_soft_delete_unaccepted_answer(
        self,
    ) -> None:
        q = Question.ask(
            title_value="操作系统死锁条件", body_value="四条件解释。", author_id=uuid4()
        )
        a_unaccepted = Answer.post(
            question_id=q.id, body_value="刷屏垃圾回复内容", author_id=uuid4()
        )
        a_gone = Answer.post(
            question_id=q.id, body_value="作者随后自删的回答", author_id=uuid4()
        )
        q_repo = FakeQuestionRepo([q])
        a_repo = FakeAnswerRepo(q_repo, [a_unaccepted, a_gone])
        r_repo = FakeReportRepo()
        create_uc = CreateReportUseCase(r_repo, q_repo, a_repo)
        resolve_uc = _make_resolve_uc(r_repo, q_repo, a_repo)

        rep_a = await create_uc.execute(
            CreateReportCommand(
                reporter_id=uuid4(),
                target_type=ReportTargetType.ANSWER,
                target_id=a_unaccepted.id,
                reason="未采纳垃圾回答测试",
            )
        )
        rep_gone = await create_uc.execute(
            CreateReportCommand(
                reporter_id=uuid4(),
                target_type=ReportTargetType.ANSWER,
                target_id=a_gone.id,
                reason="目标后被自删测试",
            )
        )
        await a_repo.soft_delete(a_gone.id, datetime.now(UTC))

        # 目标已被作者删除时，soft_delete 返回 404 且回滚保持 pending；dismiss 仍允许 200
        with pytest.raises(AnswerNotFoundError):
            await _resolve_tx(
                resolve_uc,
                r_repo,
                ResolveReportCommand(
                    report_id=rep_gone.id,
                    admin_id=uuid4(),
                    action=ReportAction.SOFT_DELETE,
                ),
            )
        assert (
            await _resolve_tx(
                resolve_uc,
                r_repo,
                ResolveReportCommand(
                    report_id=rep_gone.id,
                    admin_id=uuid4(),
                    action=ReportAction.DISMISS,
                ),
            )
        ).status is ReportStatus.DISMISSED

        # 未采纳回答管理员软删除成功
        assert (
            await _resolve_tx(
                resolve_uc,
                r_repo,
                ResolveReportCommand(
                    report_id=rep_a.id,
                    admin_id=uuid4(),
                    action=ReportAction.SOFT_DELETE,
                ),
            )
        ).status is ReportStatus.RESOLVED
        assert a_repo.items[a_unaccepted.id].is_deleted is True
