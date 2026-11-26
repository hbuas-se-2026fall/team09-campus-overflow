"""内容举报仓储的 SQLAlchemy 异步实现（F18）。"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select
from sqlalchemy import update as sql_update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.qa.domain.errors import (
    DuplicatePendingReportError,
    ReportAlreadyResolvedError,
    ReportNotFoundError,
)
from app.contexts.qa.domain.report import (
    Report,
    ReportAction,
    ReportReason,
    ReportStatus,
    ReportTargetType,
    ResolutionNote,
)
from app.contexts.qa.infrastructure.models import ReportModel


def _to_domain(model: ReportModel) -> Report:
    return Report(
        id=model.id,
        reporter_id=model.reporter_id,
        target_type=ReportTargetType(model.target_type),
        target_id=model.target_id,
        reason=ReportReason(model.reason),
        status=ReportStatus(model.status),
        created_at=model.created_at,
        resolution_action=(
            ReportAction(model.resolution_action)
            if model.resolution_action is not None
            else None
        ),
        resolution_note=(
            ResolutionNote(model.resolution_note)
            if model.resolution_note is not None
            else None
        ),
        resolved_by=model.resolved_by,
        resolved_at=model.resolved_at,
    )


def _apply_filters(
    stmt: Select[Any],
    *,
    status: ReportStatus | None,
    target_type: ReportTargetType | None,
) -> Select[Any]:
    if status is not None:
        stmt = stmt.where(ReportModel.status == status.value)
    if target_type is not None:
        stmt = stmt.where(ReportModel.target_type == target_type.value)
    return stmt


def _extract_pg_error_info(exc: IntegrityError) -> tuple[str | None, str | None]:
    orig = exc.orig
    cause = getattr(orig, "__cause__", None)
    pgcode = (
        getattr(orig, "pgcode", None)
        or getattr(orig, "sqlstate", None)
        or (getattr(cause, "sqlstate", None) if cause is not None else None)
        or (getattr(cause, "pgcode", None) if cause is not None else None)
    )
    constraint = (
        getattr(cause, "constraint_name", None) if cause is not None else None
    ) or getattr(orig, "constraint_name", None)
    return (
        pgcode if isinstance(pgcode, str) else None,
        constraint if isinstance(constraint, str) else None,
    )


class SqlAlchemyReportRepository:
    """ReportRepository 端口的 SQLAlchemy 实现。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, report: Report) -> None:
        self._session.add(
            ReportModel(
                id=report.id,
                reporter_id=report.reporter_id,
                target_type=report.target_type.value,
                target_id=report.target_id,
                reason=report.reason.value,
                status=report.status.value,
                resolution_action=(
                    report.resolution_action.value
                    if report.resolution_action is not None
                    else None
                ),
                resolution_note=(
                    report.resolution_note.value
                    if report.resolution_note is not None
                    else None
                ),
                resolved_by=report.resolved_by,
                created_at=report.created_at,
                resolved_at=report.resolved_at,
            )
        )
        try:
            await self._session.flush()
        except IntegrityError as exc:
            pgcode, constraint = _extract_pg_error_info(exc)
            if constraint == "uq_reports_pending_reporter_target" or (
                pgcode == "23505" and constraint is None
            ):
                raise DuplicatePendingReportError(
                    "您已举报过该内容，请等待管理员处理"
                ) from exc
            raise

    async def get_by_id(self, report_id: UUID) -> Report | None:
        model = (
            await self._session.execute(
                select(ReportModel)
                .where(ReportModel.id == report_id)
                .execution_options(populate_existing=True)
            )
        ).scalar_one_or_none()
        return None if model is None else _to_domain(model)

    async def list_paginated(
        self,
        *,
        page: int,
        page_size: int,
        status: ReportStatus | None = None,
        target_type: ReportTargetType | None = None,
    ) -> tuple[list[Report], int]:
        total = int(
            (
                await self._session.execute(
                    _apply_filters(
                        select(func.count()).select_from(ReportModel),
                        status=status,
                        target_type=target_type,
                    )
                )
            ).scalar_one()
        )
        offset = (page - 1) * page_size
        if total == 0 or offset >= total:
            return [], total
        stmt = (
            _apply_filters(
                select(ReportModel), status=status, target_type=target_type
            )
            .order_by(ReportModel.created_at.desc(), ReportModel.id.desc())
            .offset(offset)
            .limit(page_size)
        )
        models = (await self._session.execute(stmt)).scalars().all()
        return [_to_domain(model) for model in models], total

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
        stmt = (
            sql_update(ReportModel)
            .where(
                ReportModel.id == report_id,
                ReportModel.status == ReportStatus.PENDING.value,
            )
            .values(
                status=new_status.value,
                resolution_action=action.value,
                resolution_note=note.value if note is not None else None,
                resolved_by=resolved_by,
                resolved_at=resolved_at,
            )
            .returning(ReportModel)
            .execution_options(synchronize_session=False)
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model is not None:
            return _to_domain(model)

        existing_status = (
            await self._session.execute(
                select(ReportModel.status).where(ReportModel.id == report_id)
            )
        ).scalar_one_or_none()
        if existing_status is None:
            raise ReportNotFoundError("举报不存在")
        raise ReportAlreadyResolvedError("该举报已被处理")
