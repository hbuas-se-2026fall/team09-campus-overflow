"""qa 组合根：仓储适配器的唯一装配处。

interfaces 层只在本文件 import infrastructure；路由拿到的参数类型是 domain
端口（Protocol）。换存储实现只改本文件，路由也可用假仓储直接单测。

会话依赖统一在此声明 `scope="function"`：get_session 的退出代码（commit）
须在响应发送前执行（ADR-003）；同一请求内多个仓储依赖共享同一个会话实例
（FastAPI 依赖缓存命中同一 get_session）。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Annotated
from uuid import UUID

from fastapi import Depends

from app.contexts.course.application.ports import (
    CourseAccessReader as CourseContextAccessReader,
)
from app.contexts.course.interfaces.api.deps import get_course_access_reader
from app.contexts.discovery.interfaces.api.deps import get_notification_writer
from app.contexts.qa.application.bounty_service import BountyService
from app.contexts.qa.application.ports import (
    CourseAccessReader,
    CourseSummary,
    NotificationWriter,
)
from app.contexts.qa.domain.repository import (
    AnswerRepository,
    BountyRepository,
    CommentRepository,
    CourseLeaderboardRepository,
    PointsRepository,
    QuestionRepository,
    ReportRepository,
    TagCatalogRepository,
    UserActivityRepository,
    VoteRepository,
)
from app.contexts.qa.infrastructure.answer_repository import SqlAlchemyAnswerRepository
from app.contexts.qa.infrastructure.bounty_repository import SqlAlchemyBountyRepository
from app.contexts.qa.infrastructure.comment_repository import SqlAlchemyCommentRepository
from app.contexts.qa.infrastructure.course_leaderboard_repository import (
    SqlAlchemyCourseLeaderboardRepository,
)
from app.contexts.qa.infrastructure.points_repository import SqlAlchemyPointsRepository
from app.contexts.qa.infrastructure.question_repository import SqlAlchemyQuestionRepository
from app.contexts.qa.infrastructure.report_repository import SqlAlchemyReportRepository
from app.contexts.qa.infrastructure.tag_repository import SqlAlchemyTagCatalogRepository
from app.contexts.qa.infrastructure.user_activity_repository import (
    SqlAlchemyUserActivityRepository,
)
from app.contexts.qa.infrastructure.vote_repository import SqlAlchemyVoteRepository
from app.platform.http.deps import SessionDep


def get_question_repository(session: SessionDep) -> QuestionRepository:
    return SqlAlchemyQuestionRepository(session)


def get_answer_repository(session: SessionDep) -> AnswerRepository:
    return SqlAlchemyAnswerRepository(session)


def get_vote_repository(session: SessionDep) -> VoteRepository:
    return SqlAlchemyVoteRepository(session)


def get_comment_repository(session: SessionDep) -> CommentRepository:
    return SqlAlchemyCommentRepository(session)


def get_tag_catalog_repository(session: SessionDep) -> TagCatalogRepository:
    return SqlAlchemyTagCatalogRepository(session)


def get_user_activity_repository(session: SessionDep) -> UserActivityRepository:
    return SqlAlchemyUserActivityRepository(session)


def get_points_repository(session: SessionDep) -> PointsRepository:
    return SqlAlchemyPointsRepository(session)


def get_bounty_repository(session: SessionDep) -> BountyRepository:
    return SqlAlchemyBountyRepository(session)


def get_bounty_service(session: SessionDep) -> BountyService:
    return BountyService(
        SqlAlchemyBountyRepository(session), SqlAlchemyPointsRepository(session)
    )


class _CourseAccessAdapter:
    """F17 防腐层适配器：将 course 已发布语言映射为 qa 应用层窄端口。"""

    def __init__(self, reader: CourseContextAccessReader) -> None:
        self._reader = reader

    async def get_summary(self, course_id: UUID) -> CourseSummary | None:
        item = await self._reader.get_summary(course_id)
        if item is None:
            return None
        return CourseSummary(
            course_id=item.course_id,
            code=item.code,
            name=item.name,
            semester=item.semester,
        )

    async def get_summaries(
        self, course_ids: Iterable[UUID]
    ) -> dict[UUID, CourseSummary]:
        items = await self._reader.get_summaries(course_ids)
        return {
            cid: CourseSummary(
                course_id=summary.course_id,
                code=summary.code,
                name=summary.name,
                semester=summary.semester,
            )
            for cid, summary in items.items()
        }

    async def is_enrolled(self, course_id: UUID, student_id: UUID) -> bool:
        return await self._reader.is_enrolled(course_id, student_id)


def get_qa_course_access_reader(session: SessionDep) -> CourseAccessReader:
    return _CourseAccessAdapter(get_course_access_reader(session))


def get_course_leaderboard_repository(
    session: SessionDep,
) -> CourseLeaderboardRepository:
    return SqlAlchemyCourseLeaderboardRepository(session)


def get_report_repository(session: SessionDep) -> ReportRepository:
    return SqlAlchemyReportRepository(session)


QuestionRepo = Annotated[QuestionRepository, Depends(get_question_repository)]
AnswerRepo = Annotated[AnswerRepository, Depends(get_answer_repository)]
VoteRepo = Annotated[VoteRepository, Depends(get_vote_repository)]
CommentRepo = Annotated[CommentRepository, Depends(get_comment_repository)]
TagCatalogRepo = Annotated[TagCatalogRepository, Depends(get_tag_catalog_repository)]
UserActivityRepo = Annotated[
    UserActivityRepository, Depends(get_user_activity_repository)
]
# F04：qa 只声明写入端口；适配器工厂来自 discovery interfaces（interfaces→interfaces 护栏）
NotificationWriterDep = Annotated[
    NotificationWriter, Depends(get_notification_writer)
]
PointsRepo = Annotated[PointsRepository, Depends(get_points_repository)]
BountyRepo = Annotated[BountyRepository, Depends(get_bounty_repository)]
BountyServiceDep = Annotated[BountyService, Depends(get_bounty_service)]
CourseAccessReaderDep = Annotated[
    CourseAccessReader, Depends(get_qa_course_access_reader)
]
CourseLeaderboardRepo = Annotated[
    CourseLeaderboardRepository, Depends(get_course_leaderboard_repository)
]
ReportRepo = Annotated[ReportRepository, Depends(get_report_repository)]
