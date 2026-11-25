"""课程贡献排行榜查询用例（F17：基于课程下活跃问答的只读聚合）。"""

from __future__ import annotations

from app.contexts.qa.application.ports import CourseAccessReader
from app.contexts.qa.application.queries import (
    CourseLeaderboardView,
    GetCourseLeaderboardQuery,
)
from app.contexts.qa.domain.errors import CourseNotFoundError
from app.contexts.qa.domain.repository import CourseLeaderboardRepository
from app.shared.errors import DomainValidationError

_LEADERBOARD_MAX_LIMIT = 50


class GetCourseLeaderboardUseCase:
    """按课程聚合答主采纳数与净赞数排名（课程不存在返回 404）。"""

    def __init__(
        self,
        course_reader: CourseAccessReader,
        leaderboard_repo: CourseLeaderboardRepository,
    ) -> None:
        self._course_reader = course_reader
        self._leaderboard_repo = leaderboard_repo

    async def execute(self, query: GetCourseLeaderboardQuery) -> CourseLeaderboardView:
        if not (1 <= query.limit <= _LEADERBOARD_MAX_LIMIT):
            raise DomainValidationError(
                f"榜单条数 limit 必须在 1~{_LEADERBOARD_MAX_LIMIT} 之间"
            )
        summary = await self._course_reader.get_summary(query.course_id)
        if summary is None:
            raise CourseNotFoundError("课程不存在")
        entries = await self._leaderboard_repo.list_top_contributors(
            query.course_id, limit=query.limit
        )
        return CourseLeaderboardView(
            course_id=summary.course_id,
            course_code=summary.code,
            course_name=summary.name,
            entries=entries,
        )
