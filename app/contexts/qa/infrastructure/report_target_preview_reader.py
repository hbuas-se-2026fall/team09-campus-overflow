"""被举报目标批量只读预览读取器（F18：最多 2 条 IN 查询，零 N+1，空输入 0 SQL）。"""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.qa.domain.report import ReportTargetType
from app.contexts.qa.domain.repository import ReportTargetPreview
from app.contexts.qa.infrastructure.models import AnswerModel, QuestionModel


class SqlAlchemyReportTargetPreviewReader:
    """基于 SQLAlchemy 的举报目标批量预览读取器（不按 deleted_at 过滤，供历史回溯）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_previews(
        self, targets: Iterable[tuple[ReportTargetType, UUID]]
    ) -> dict[tuple[ReportTargetType, UUID], ReportTargetPreview]:
        question_ids: list[UUID] = []
        seen_questions: set[UUID] = set()
        answer_ids: list[UUID] = []
        seen_answers: set[UUID] = set()

        for target_type, target_id in targets:
            if target_type is ReportTargetType.QUESTION:
                if target_id not in seen_questions:
                    seen_questions.add(target_id)
                    question_ids.append(target_id)
            elif target_type is ReportTargetType.ANSWER:
                if target_id not in seen_answers:
                    seen_answers.add(target_id)
                    answer_ids.append(target_id)

        if not question_ids and not answer_ids:
            return {}

        previews: dict[tuple[ReportTargetType, UUID], ReportTargetPreview] = {}

        if question_ids:
            q_rows = (
                await self._session.execute(
                    select(
                        QuestionModel.id,
                        QuestionModel.title,
                        QuestionModel.body,
                        QuestionModel.deleted_at,
                    ).where(QuestionModel.id.in_(question_ids))
                )
            ).all()
            for qid, title, body, deleted_at in q_rows:
                previews[(ReportTargetType.QUESTION, qid)] = ReportTargetPreview(
                    question_id=qid,
                    title=title,
                    body=body,
                    is_deleted=deleted_at is not None,
                )

        if answer_ids:
            a_rows = (
                await self._session.execute(
                    select(
                        AnswerModel.id,
                        AnswerModel.question_id,
                        AnswerModel.body,
                        AnswerModel.deleted_at,
                        QuestionModel.title,
                        QuestionModel.deleted_at,
                    )
                    .select_from(AnswerModel)
                    .outerjoin(QuestionModel, QuestionModel.id == AnswerModel.question_id)
                    .where(AnswerModel.id.in_(answer_ids))
                )
            ).all()
            for (
                aid,
                question_id,
                a_body,
                a_deleted_at,
                q_title,
                q_deleted_at,
            ) in a_rows:
                previews[(ReportTargetType.ANSWER, aid)] = ReportTargetPreview(
                    question_id=question_id,
                    title=q_title,
                    body=a_body,
                    is_deleted=(a_deleted_at is not None or q_deleted_at is not None),
                )

        return previews
