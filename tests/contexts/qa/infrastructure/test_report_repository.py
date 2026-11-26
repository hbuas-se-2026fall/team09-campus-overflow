"""F18 内容举报仓储 PG 集成测试。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from app.contexts.qa.domain.errors import (
    DuplicatePendingReportError,
    ReportAlreadyResolvedError,
    ReportNotFoundError,
)
from app.contexts.qa.domain.report import (
    Report,
    ReportAction,
    ReportStatus,
    ReportTargetType,
    ResolutionNote,
)
from app.contexts.qa.infrastructure.models import ReportModel
from app.contexts.qa.infrastructure.report_repository import (
    SqlAlchemyReportRepository,
)
from app.shared.engine import session_factory

pytestmark = pytest.mark.integration


async def test_report_repository_partial_unique_check_and_conditional_resolve() -> None:
    reporter_id = uuid.uuid4()
    admin_id = uuid.uuid4()
    target_q = uuid.uuid4()
    target_a = uuid.uuid4()

    created_ids: list[uuid.UUID] = []
    try:
        base = datetime(2026, 11, 25, 10, 0, tzinfo=UTC)
        r1 = Report.file(
            reporter_id=reporter_id,
            target_type=ReportTargetType.QUESTION,
            target_id=target_q,
            reason="首次举报问题包含无关引流广告",
        )
        r1.created_at = base
        r2 = Report.file(
            reporter_id=reporter_id,
            target_type=ReportTargetType.ANSWER,
            target_id=target_a,
            reason="首次举报回答存在抄袭拼凑",
        )
        r2.created_at = base + timedelta(seconds=5)
        created_ids.extend([r1.id, r2.id])

        async with session_factory() as session:
            repo = SqlAlchemyReportRepository(session)
            await repo.add(r1)
            await repo.add(r2)
            await session.commit()

        # 重复待处理举报撞部分唯一索引 -> DuplicatePendingReportError（不泄露 exc.orig）
        async with session_factory() as session:
            repo = SqlAlchemyReportRepository(session)
            dup = Report.file(
                reporter_id=reporter_id,
                target_type=ReportTargetType.QUESTION,
                target_id=target_q,
                reason="再次举报同一待处理目标",
            )
            with pytest.raises(DuplicatePendingReportError) as exc_info:
                await repo.add(dup)
            assert "uq_reports_pending_reporter_target" not in str(exc_info.value)
            assert "DETAIL" not in str(exc_info.value)
            await session.rollback()

        # 库级 CHECK 约束拒收 comment 目标
        async with session_factory() as session:
            with pytest.raises(IntegrityError):
                await session.execute(
                    text(
                        "INSERT INTO reports "
                        "(id, reporter_id, target_type, target_id, reason, status) "
                        "VALUES (:id, :rid, 'comment', :tid, '非法目标类型测试', 'pending')"
                    ),
                    {"id": uuid.uuid4(), "rid": reporter_id, "tid": target_q},
                )
            await session.rollback()

        # resolve_pending 条件更新 + 重复处置 409 + 缺失 404
        async with session_factory() as session:
            repo = SqlAlchemyReportRepository(session)
            resolved = await repo.resolve_pending(
                report_id=r1.id,
                new_status=ReportStatus.DISMISSED,
                action=ReportAction.DISMISS,
                note=ResolutionNote("核实后不构成违规"),
                resolved_by=admin_id,
                resolved_at=datetime.now(UTC),
            )
            await session.commit()
            assert resolved.status is ReportStatus.DISMISSED

        async with session_factory() as session:
            repo = SqlAlchemyReportRepository(session)
            with pytest.raises(ReportAlreadyResolvedError):
                await repo.resolve_pending(
                    report_id=r1.id,
                    new_status=ReportStatus.RESOLVED,
                    action=ReportAction.SOFT_DELETE,
                    note=None,
                    resolved_by=admin_id,
                    resolved_at=datetime.now(UTC),
                )
            with pytest.raises(ReportNotFoundError):
                await repo.resolve_pending(
                    report_id=uuid.uuid4(),
                    new_status=ReportStatus.DISMISSED,
                    action=ReportAction.DISMISS,
                    note=None,
                    resolved_by=admin_id,
                    resolved_at=datetime.now(UTC),
                )

        # 驳回后同一举报人可对同一目标再次举报
        r3 = Report.file(
            reporter_id=reporter_id,
            target_type=ReportTargetType.QUESTION,
            target_id=target_q,
            reason="驳回后重新提交的合法举报",
        )
        r3.created_at = base + timedelta(seconds=10)
        created_ids.append(r3.id)
        async with session_factory() as session:
            repo = SqlAlchemyReportRepository(session)
            await repo.add(r3)
            await session.commit()

        # list_paginated + COUNT 对账
        async with session_factory() as session:
            repo = SqlAlchemyReportRepository(session)
            pending_db = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(ReportModel)
                        .where(ReportModel.status == "pending")
                    )
                ).scalar_one()
            )
            pending_items, pending_total = await repo.list_paginated(
                page=1, page_size=50, status=ReportStatus.PENDING
            )
            assert pending_total == pending_db
            assert [r.id for r in pending_items if r.id in created_ids] == [r3.id, r2.id]
    finally:
        async with session_factory() as session:
            await session.execute(
                delete(ReportModel).where(ReportModel.id.in_(created_ids))
            )
            await session.commit()
