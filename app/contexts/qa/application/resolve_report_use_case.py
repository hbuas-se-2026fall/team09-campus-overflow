"""管理员处置举报用例（F18：reports → questions DAG 锁序 + 事务内策略执行）。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from app.contexts.qa.application.commands import ResolveReportCommand
from app.contexts.qa.application.report_resolution_handlers import (
    ReportResolutionHandler,
)
from app.contexts.qa.domain.errors import (
    InvalidReportActionError,
    ReportAlreadyResolvedError,
    ReportNotFoundError,
)
from app.contexts.qa.domain.report import (
    Report,
    ReportAction,
    ReportStatus,
    normalize_resolution_note,
)
from app.contexts.qa.domain.repository import ReportRepository


class ResolveReportUseCase:
    """先条件抢占 pending 举报，再同事务执行动作处理器；失败整笔回滚保持 pending。"""

    def __init__(
        self,
        report_repo: ReportRepository,
        handlers: Mapping[ReportAction, ReportResolutionHandler],
    ) -> None:
        self._report_repo = report_repo
        self._handlers = handlers

    async def execute(self, command: ResolveReportCommand) -> Report:
        note = normalize_resolution_note(command.note)
        report = await self._report_repo.get_by_id(command.report_id)
        if report is None:
            raise ReportNotFoundError("举报不存在")
        if report.status is not ReportStatus.PENDING:
            raise ReportAlreadyResolvedError("该举报已被处理")

        handler = self._handlers.get(command.action)
        if handler is None:
            raise InvalidReportActionError(f"不支持的处理动作：{command.action}")

        new_status = handler.validate_target(report)
        resolved = await self._report_repo.resolve_pending(
            report_id=report.id,
            new_status=new_status,
            action=command.action,
            note=note,
            resolved_by=command.admin_id,
            resolved_at=datetime.now(UTC),
        )
        await handler.apply(report)
        return resolved
