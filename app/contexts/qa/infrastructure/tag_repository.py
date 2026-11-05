from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.qa.domain.tag import Tag
from app.contexts.qa.infrastructure.models import TagModel


class SqlAlchemyTagCatalogRepository:
    """TagCatalogRepository 端口的 SQLAlchemy 实现（迭代 4，US-T01/T02）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _find(self, key: str) -> TagModel | None:
        stmt = select(TagModel).where(TagModel.key == key)
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def get_or_create(self, tag: Tag) -> Tag:
        # 随用随建（T02）：先按归并键查既有行（key 列唯一索引）
        model = await self._find(tag.key)
        if model is not None:
            return Tag(value=model.name, id=model.id)
        try:
            # savepoint 隔离插入：并发双插撞唯一索引时仅回滚本 savepoint，
            # 外层事务（含同请求已写的其它标签行）不受影响
            async with self._session.begin_nested():
                row = TagModel(id=uuid4(), name=tag.value, key=tag.key)
                self._session.add(row)
                await self._session.flush()
        except IntegrityError:
            # 竞败方：他事务已建同键行 → 重查复用（幂等，不报错）。
            # 键由应用单侧计算（key 列），与库判定恒等，重查必命中
            model = await self._find(tag.key)
            if model is None:  # 理论不可达（撞唯一索引必有行）；防御性上抛
                raise
            return Tag(value=model.name, id=model.id)
        return Tag(value=tag.value, id=row.id)

    async def list_all(self) -> list[Tag]:
        models = (
            (await self._session.execute(select(TagModel).order_by(TagModel.name)))
            .scalars()
            .all()
        )
        return [Tag(value=m.name, id=m.id) for m in models]
