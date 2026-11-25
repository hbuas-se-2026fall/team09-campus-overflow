"""列表/详情用例的输入查询（只读，与 commands.py 的写命令对位）。"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from app.contexts.qa.domain.repository import (
    CourseLeaderboardEntry,
    QuestionFilter,
    QuestionSort,
)


@dataclass(frozen=True, slots=True)
class ListQuestionsQuery:
    """列表查询参数（ge/le 边界与 sort 枚举校验由路由层 Query 完成后传入）。"""

    page: int
    page_size: int
    sort: QuestionSort = QuestionSort.LATEST
    filters: QuestionFilter | None = None


@dataclass(frozen=True, slots=True)
class GetQuestionQuery:
    """详情查询参数。"""

    question_id: UUID


@dataclass(frozen=True, slots=True)
class ListRelatedQuestionsQuery:
    """相关问题查询（F03）：limit 边界（1~10）由路由 Query 校验后传入。"""

    question_id: UUID
    limit: int = 5


@dataclass(frozen=True, slots=True)
class GetCourseLeaderboardQuery:
    """课程贡献排行榜查询（F17）：limit 边界 1~50。"""

    course_id: UUID
    limit: int = 20


@dataclass(frozen=True, slots=True)
class CourseLeaderboardView:
    """课程贡献排行榜视图（F17）。"""

    course_id: UUID
    course_code: str
    course_name: str
    entries: list[CourseLeaderboardEntry]
