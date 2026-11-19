"""相关问题用例：标签共现推荐（F03，只读）。

排序与截断委托仓储 SQL；本用例只负责存在性判定（404 语义与详情一致）。
"""

from __future__ import annotations

from app.contexts.qa.application.queries import ListRelatedQuestionsQuery
from app.contexts.qa.domain.question import Question
from app.contexts.qa.domain.repository import QuestionRepository


class ListRelatedQuestionsUseCase:
    """相关问题读取：问题不存在返回 None（路由层转 404）。"""

    def __init__(self, repository: QuestionRepository) -> None:
        self._repository = repository

    async def execute(self, query: ListRelatedQuestionsQuery) -> list[Question] | None:
        question = await self._repository.get_by_id(query.question_id)
        if question is None:
            return None
        return await self._repository.list_related(query.question_id, query.limit)
