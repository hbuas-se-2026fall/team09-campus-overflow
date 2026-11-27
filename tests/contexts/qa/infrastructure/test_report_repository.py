"""F18 内容举报仓储 PG 集成测试。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from app.contexts.identity.infrastructure.models import UserModel
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
from app.contexts.qa.infrastructure.models import (
    AnswerModel,
    QuestionModel,
    ReportModel,
)
from app.contexts.qa.infrastructure.report_repository import (
    SqlAlchemyReportRepository,
)
from app.contexts.qa.infrastructure.report_target_preview_reader import (
    SqlAlchemyReportTargetPreviewReader,
)
from app.shared.engine import engine, session_factory

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


async def test_report_target_preview_reader_sql_count_and_soft_delete() -> None:
    """批量预览空输入 0 SQL、混合 batch <= 2 SQL，且保留软删对象正文。"""
    from sqlalchemy import event

    author_id = uuid.uuid4()
    q_live_id = uuid.uuid4()
    q_del_id = uuid.uuid4()
    a_live_id = uuid.uuid4()
    a_under_del_q_id = uuid.uuid4()
    now = datetime.now(UTC)

    try:
        async with session_factory() as session:
            session.add(
                UserModel(
                    id=author_id,
                    email=f"preview-{uuid.uuid4().hex[:8]}@campus.edu.cn",
                    password_hash="$2b$12$abcdefghijklmnopqrstuv",
                )
            )
            session.add_all(
                [
                    QuestionModel(
                        id=q_live_id,
                        title="操作系统页面置换算法 FIFO Belady 异常",
                        body="为什么增加物理页帧反而可能提高缺页率？",
                        author_id=author_id,
                    ),
                    QuestionModel(
                        id=q_del_id,
                        title="已被管理员软删除的历史问题标题",
                        body="该历史问题正文在软删后仍可供工单回溯。",
                        author_id=author_id,
                        deleted_at=now,
                    ),
                ]
            )
            await session.flush()
            session.add_all(
                [
                    AnswerModel(
                        id=a_live_id,
                        question_id=q_live_id,
                        body="FIFO 不满足栈算法包含性，LRU 无此异常。",
                        author_id=author_id,
                        deleted_at=now,
                    ),
                    AnswerModel(
                        id=a_under_del_q_id,
                        question_id=q_del_id,
                        body="父问题已软删的回答正文示例。",
                        author_id=author_id,
                    ),
                ]
            )
            await session.commit()

        sql_log: list[str] = []

        def _capture(conn, cursor, statement, parameters, context, executemany):  # type: ignore[no-untyped-def]
            sql_log.append(statement)

        async with session_factory() as session:
            reader = SqlAlchemyReportTargetPreviewReader(session)
            event.listen(engine.sync_engine, "before_cursor_execute", _capture)
            try:
                assert await reader.get_previews([]) == {}
                assert sql_log == []

                batch = await reader.get_previews(
                    [
                        (ReportTargetType.QUESTION, q_live_id),
                        (ReportTargetType.QUESTION, q_live_id),  # 重复去重
                        (ReportTargetType.QUESTION, q_del_id),
                        (ReportTargetType.ANSWER, a_live_id),
                        (ReportTargetType.ANSWER, a_under_del_q_id),
                    ]
                )
            finally:
                event.remove(engine.sync_engine, "before_cursor_execute", _capture)

        assert len(sql_log) == 2
        q_live_prev = batch[(ReportTargetType.QUESTION, q_live_id)]
        assert q_live_prev.question_id == q_live_id
        assert q_live_prev.title == "操作系统页面置换算法 FIFO Belady 异常"
        assert q_live_prev.body == "为什么增加物理页帧反而可能提高缺页率？"
        assert q_live_prev.is_deleted is False

        q_del_prev = batch[(ReportTargetType.QUESTION, q_del_id)]
        assert q_del_prev.body == "该历史问题正文在软删后仍可供工单回溯。"
        assert q_del_prev.is_deleted is True

        a_live_prev = batch[(ReportTargetType.ANSWER, a_live_id)]
        assert a_live_prev.question_id == q_live_id
        assert a_live_prev.title == "操作系统页面置换算法 FIFO Belady 异常"
        assert a_live_prev.body == "FIFO 不满足栈算法包含性，LRU 无此异常。"
        assert a_live_prev.is_deleted is True

        a_under_del_prev = batch[(ReportTargetType.ANSWER, a_under_del_q_id)]
        assert a_under_del_prev.question_id == q_del_id
        assert a_under_del_prev.title == "已被管理员软删除的历史问题标题"
        assert a_under_del_prev.is_deleted is True
    finally:
        async with session_factory() as session:
            await session.execute(
                delete(QuestionModel).where(QuestionModel.id.in_([q_live_id, q_del_id]))
            )
            await session.execute(
                delete(UserModel).where(UserModel.id == author_id)
            )
            await session.commit()
