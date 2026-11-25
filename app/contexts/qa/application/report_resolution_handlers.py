"""举报处置动作 OCP 策略映射（F18：3×2 矩阵，不修改既有 Close/Delete 用例主干）。"""

from __future__ import annotations

from typing import Protocol

from app.contexts.qa.application.bounty_service import BountyService
from app.contexts.qa.domain.errors import (
    AnswerNotFoundError,
    InvalidReportActionError,
    QuestionNotFoundError,
)
from app.contexts.qa.domain.report import (
    Report,
    ReportAction,
    ReportStatus,
    ReportTargetType,
)
from app.contexts.qa.domain.repository import AnswerRepository, QuestionRepository


class ReportResolutionHandler(Protocol):
    """举报处置动作策略端口：先校验动作兼容性，再在事务内执行内容副作用。"""

    def validate_target(self, report: Report) -> ReportStatus:
        """校验动作与目标类型兼容性并返回工单目标终态。"""
        ...

    async def apply(self, report: Report) -> None:
        """同事务执行内容侧副作用（如关贴/软删除与悬赏退款）。"""
        ...


class DismissReportHandler:
    """驳回举报：不对目标内容做任何修改（目标已被作者删除时同样允许 200 驳回）。"""

    def validate_target(self, report: Report) -> ReportStatus:
        return ReportStatus.DISMISSED

    async def apply(self, report: Report) -> None:
        return None


class CloseQuestionReportHandler:
    """管理员关闭被举报问题：仅允许 question；已关闭或含采纳答案时守卫 409。"""

    def __init__(
        self,
        question_repo: QuestionRepository,
        bounty_service: BountyService | None = None,
    ) -> None:
        self._question_repo = question_repo
        self._bounty_service = bounty_service

    def validate_target(self, report: Report) -> ReportStatus:
        if report.target_type is not ReportTargetType.QUESTION:
            raise InvalidReportActionError("仅问题类型举报支持关闭问题动作")
        return ReportStatus.RESOLVED

    async def apply(self, report: Report) -> None:
        question = await self._question_repo.get_by_id(
            report.target_id, for_update=True
        )
        if question is None:
            raise QuestionNotFoundError("问题不存在")
        question.close()
        await self._question_repo.update(question)
        if self._bounty_service is not None:
            await self._bounty_service.refund_on_close(question.id)


class SoftDeleteReportHandler:
    """管理员软删除被举报内容：绕开作者校验，仍严守 F13 D2（已采纳不可删 409）与悬赏退款。"""

    def __init__(
        self,
        question_repo: QuestionRepository,
        answer_repo: AnswerRepository,
        bounty_service: BountyService | None = None,
    ) -> None:
        self._question_repo = question_repo
        self._answer_repo = answer_repo
        self._bounty_service = bounty_service

    def validate_target(self, report: Report) -> ReportStatus:
        return ReportStatus.RESOLVED

    async def apply(self, report: Report) -> None:
        if report.target_type is ReportTargetType.QUESTION:
            await self._delete_question(report)
        else:
            await self._delete_answer(report)

    async def _delete_question(self, report: Report) -> None:
        question = await self._question_repo.get_by_id(
            report.target_id, for_update=True
        )
        if question is None:
            raise QuestionNotFoundError("问题不存在")
        question.soft_delete()
        assert question.deleted_at is not None
        deleted = await self._question_repo.soft_delete(
            question.id, question.deleted_at
        )
        if deleted and self._bounty_service is not None:
            await self._bounty_service.refund_on_delete(question.id)

    async def _delete_answer(self, report: Report) -> None:
        answer = await self._answer_repo.get_by_id(report.target_id)
        if answer is None:
            raise AnswerNotFoundError("回答不存在")
        question = await self._question_repo.get_by_id(
            answer.question_id, for_update=True
        )
        if question is None:
            raise QuestionNotFoundError("问题不存在")
        answer = await self._answer_repo.get_by_id(report.target_id)
        if answer is None:
            raise AnswerNotFoundError("回答不存在")
        answer.soft_delete()
        assert answer.deleted_at is not None
        await self._answer_repo.soft_delete(answer.id, answer.deleted_at)


def build_report_resolution_handlers(
    *,
    question_repo: QuestionRepository,
    answer_repo: AnswerRepository,
    bounty_service: BountyService | None = None,
) -> dict[ReportAction, ReportResolutionHandler]:
    """构造动作策略映射表（OCP：扩展新动作仅追加映射项）。"""
    return {
        ReportAction.DISMISS: DismissReportHandler(),
        ReportAction.CLOSE_QUESTION: CloseQuestionReportHandler(
            question_repo, bounty_service
        ),
        ReportAction.SOFT_DELETE: SoftDeleteReportHandler(
            question_repo, answer_repo, bounty_service
        ),
    }
