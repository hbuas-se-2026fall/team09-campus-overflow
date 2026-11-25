"""管理员分页查询举报列表用例（F18）。"""

from __future__ import annotations

import math

from app.contexts.qa.application.queries import ListReportsQuery, ListReportsResult
from app.contexts.qa.domain.repository import ReportRepository
from app.shared.errors import DomainValidationError


class ListReportsUseCase:
    """分页列出举报工单，元数据与列表同口径。"""

    def __init__(self, report_repo: ReportRepository) -> None:
        self._report_repo = report_repo

    async def execute(self, query: ListReportsQuery) -> ListReportsResult:
        if query.page < 1:
            raise DomainValidationError("页码 page 必须 >= 1")
        if not (1 <= query.page_size <= 100):
            raise DomainValidationError("每页条数 page_size 必须在 1~100 之间")

        items, total = await self._report_repo.list_paginated(
            page=query.page,
            page_size=query.page_size,
            status=query.status,
            target_type=query.target_type,
        )
        return ListReportsResult(
            items=items,
            total=total,
            page=query.page,
            page_size=query.page_size,
            total_pages=math.ceil(total / query.page_size) if total else 0,
        )
