"""课程贡献排行榜路由（F17，挂载于 /api/v1/courses/{course_id}/leaderboard）。"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Query

from app.contexts.identity.application.ports import pick_summary_display_name
from app.contexts.identity.interfaces.api.deps import UserSummaryReaderDep
from app.contexts.qa.application.get_course_leaderboard_use_case import (
    GetCourseLeaderboardUseCase,
)
from app.contexts.qa.application.queries import GetCourseLeaderboardQuery
from app.contexts.qa.interfaces.api.deps import (
    CourseAccessReaderDep,
    CourseLeaderboardRepo,
)
from app.contexts.qa.interfaces.api.schemas import (
    CourseLeaderboardEntryResponse,
    CourseLeaderboardResponse,
)

course_leaderboard_router = APIRouter(prefix="/api/v1/courses", tags=["courses"])


@course_leaderboard_router.get(
    "/{course_id}/leaderboard",
    response_model=CourseLeaderboardResponse,
    summary="课程贡献排行榜（公开，基于课程下被采纳回答数与净赞数聚合，课程不存在 404）",
)
async def get_course_leaderboard(
    course_id: UUID,
    course_reader: CourseAccessReaderDep,
    leaderboard_repo: CourseLeaderboardRepo,
    summary_reader: UserSummaryReaderDep,
    limit: Annotated[int, Query(ge=1, le=50, description="返回条数，1~50")] = 20,
) -> CourseLeaderboardResponse:
    view = await GetCourseLeaderboardUseCase(course_reader, leaderboard_repo).execute(
        GetCourseLeaderboardQuery(course_id=course_id, limit=limit)
    )
    summaries = await summary_reader.get_summaries(
        entry.user_id for entry in view.entries
    )
    return CourseLeaderboardResponse(
        course_id=view.course_id,
        course_code=view.course_code,
        course_name=view.course_name,
        entries=[
            CourseLeaderboardEntryResponse(
                user_id=entry.user_id,
                display_name=pick_summary_display_name(summaries, entry.user_id),
                accepted_count=entry.accepted_count,
                net_votes=entry.net_votes,
                answer_count=entry.answer_count,
                rank=entry.rank,
            )
            for entry in view.entries
        ],
    )
