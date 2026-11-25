"""提交内容举报用例（F18）。"""

from __future__ import annotations

from app.contexts.qa.application.commands import CreateReportCommand
from app.contexts.qa.domain.errors import AnswerNotFoundError, QuestionNotFoundError
from app.contexts.qa.domain.report import Report, ReportReason, ReportTargetType
from app.contexts.qa.domain.repository import (
    AnswerRepository,
    QuestionRepository,
    ReportRepository,
)


class CreateReportUseCase:
    """校验理由与活跃目标存在性后创建 pending 举报（重复 pending 由库级兜底 409）。"""

    def __init__(
        self,
        report_repo: ReportRepository,
        question_repo: QuestionRepository,
        answer_repo: AnswerRepository,
    ) -> None:
        self._report_repo = report_repo
        self._question_repo = question_repo
        self._answer_repo = answer_repo

    async def execute(self, command: CreateReportCommand) -> Report:
        reason = ReportReason(command.reason)
        if command.target_type is ReportTargetType.QUESTION:
            if await self._question_repo.get_by_id(command.target_id) is None:
                raise QuestionNotFoundError("问题不存在")
        else:
            if await self._answer_repo.get_by_id(command.target_id) is None:
                raise AnswerNotFoundError("回答不存在")

        report = Report.file(
            reporter_id=command.reporter_id,
            target_type=command.target_type,
            target_id=command.target_id,
            reason=reason.value,
        )
        await self._report_repo.add(report)
        return report
