"""内容举报与管理员审核后台路由（F18，薄壳，零业务分支与 try/except）。"""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Query, status

from app.contexts.identity.application.ports import (
    UserSummary,
    pick_summary_display_name,
)
from app.contexts.identity.interfaces.api.deps import (
    AdminUser,
    CurrentUser,
    UserSummaryReaderDep,
)
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
from app.contexts.qa.domain.report import Report, ReportStatus, ReportTargetType
from app.contexts.qa.interfaces.api.deps import (
    AnswerRepo,
    BountyServiceDep,
    QuestionRepo,
    ReportRepo,
)
from app.contexts.qa.interfaces.api.schemas import (
    CreateReportRequest,
    ReportListResponse,
    ReportResponse,
    ResolveReportRequest,
)

reports_router = APIRouter(prefix="/api/v1/reports", tags=["reports"])
admin_reports_router = APIRouter(prefix="/api/v1/admin/reports", tags=["admin"])


def _report_response(
    report: Report,
    *,
    reporter_name: str,
    resolved_by_name: str | None = None,
) -> ReportResponse:
    return ReportResponse(
        id=report.id,
        reporter_id=report.reporter_id,
        reporter_name=reporter_name,
        target_type=report.target_type,
        target_id=report.target_id,
        reason=report.reason.value,
        status=report.status,
        resolution_action=report.resolution_action,
        resolution_note=(
            report.resolution_note.value if report.resolution_note is not None else None
        ),
        resolved_by=report.resolved_by,
        resolved_by_name=resolved_by_name,
        created_at=report.created_at,
        resolved_at=report.resolved_at,
    )


def _format_with_summaries(
    report: Report, summaries: dict[UUID, UserSummary]
) -> ReportResponse:
    resolved_by_name = (
        pick_summary_display_name(summaries, report.resolved_by)
        if report.resolved_by is not None
        else None
    )
    return _report_response(
        report,
        reporter_name=pick_summary_display_name(summaries, report.reporter_id),
        resolved_by_name=resolved_by_name,
    )


@reports_router.post(
    "",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
    summary="提交内容举报（登录用户，仅 question/answer；重复待处理举报 409）",
)
async def create_report(
    payload: CreateReportRequest,
    user: CurrentUser,
    reports: ReportRepo,
    questions: QuestionRepo,
    answers: AnswerRepo,
) -> ReportResponse:
    report = await CreateReportUseCase(reports, questions, answers).execute(
        CreateReportCommand(
            reporter_id=user.id,
            target_type=payload.target_type,
            target_id=payload.target_id,
            reason=payload.reason,
        )
    )
    return _report_response(report, reporter_name=user.display_name)


@admin_reports_router.get(
    "",
    response_model=ReportListResponse,
    summary="管理员分页查询举报列表（仅 admin；支持按 status/target_type 筛选）",
)
async def list_reports(
    _admin: AdminUser,
    reports: ReportRepo,
    summary_reader: UserSummaryReaderDep,
    page: Annotated[int, Query(ge=1, description="页码，从 1 起")] = 1,
    page_size: Annotated[int, Query(ge=1, le=100, description="每页条数，上限 100")] = 20,
    status_filter: Annotated[
        ReportStatus | Literal["all"],
        Query(
            alias="status",
            description="按状态筛选：pending（默认）/ resolved / dismissed / all",
        ),
    ] = ReportStatus.PENDING,
    target_type: Annotated[
        ReportTargetType | None,
        Query(description="按目标类型筛选：question / answer"),
    ] = None,
) -> ReportListResponse:
    resolved_status = None if status_filter == "all" else ReportStatus(status_filter)
    result = await ListReportsUseCase(reports).execute(
        ListReportsQuery(
            page=page,
            page_size=page_size,
            status=resolved_status,
            target_type=target_type,
        )
    )
    user_ids: list[UUID] = []
    for item in result.items:
        user_ids.append(item.reporter_id)
        if item.resolved_by is not None:
            user_ids.append(item.resolved_by)
    summaries = await summary_reader.get_summaries(user_ids)
    return ReportListResponse(
        items=[_format_with_summaries(item, summaries) for item in result.items],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )


@admin_reports_router.post(
    "/{report_id}/resolve",
    response_model=ReportResponse,
    summary="管理员处置举报（仅 admin；支持 dismiss / close_question / soft_delete）",
)
async def resolve_report(
    report_id: UUID,
    payload: ResolveReportRequest,
    admin: AdminUser,
    reports: ReportRepo,
    questions: QuestionRepo,
    answers: AnswerRepo,
    bounty_service: BountyServiceDep,
    summary_reader: UserSummaryReaderDep,
) -> ReportResponse:
    handlers = build_report_resolution_handlers(
        question_repo=questions,
        answer_repo=answers,
        bounty_service=bounty_service,
    )
    resolved = await ResolveReportUseCase(reports, handlers).execute(
        ResolveReportCommand(
            report_id=report_id,
            admin_id=admin.id,
            action=payload.action,
            note=payload.note,
        )
    )
    summaries = await summary_reader.get_summaries([resolved.reporter_id])
    return _report_response(
        resolved,
        reporter_name=pick_summary_display_name(summaries, resolved.reporter_id),
        resolved_by_name=admin.display_name,
    )
