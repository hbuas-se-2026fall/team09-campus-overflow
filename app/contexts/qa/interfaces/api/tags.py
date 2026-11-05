"""标签路由：目录浏览（访客可用）。"""

from __future__ import annotations

from fastapi import APIRouter

from app.contexts.qa.application.list_tags_use_case import ListTagsUseCase
from app.contexts.qa.interfaces.api.deps import TagCatalogRepo
from app.contexts.qa.interfaces.api.schemas import TagListResponse

tags_router = APIRouter(prefix="/api/v1/tags", tags=["tags"])


@tags_router.get(
    "",
    response_model=TagListResponse,
    summary="标签目录（访客可用，US-T01；码点序、同名唯一）",
)
async def list_tags(
    tag_catalog: TagCatalogRepo,
) -> TagListResponse:
    tags = await ListTagsUseCase(tag_catalog).execute()
    return TagListResponse(tags=[t.value for t in tags])
