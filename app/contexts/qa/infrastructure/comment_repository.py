from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.qa.domain.comment import Comment, CommentTarget
from app.contexts.qa.domain.value_objects import Body
from app.contexts.qa.infrastructure.models import CommentModel


def _to_domain(model: CommentModel) -> Comment:
    return Comment(
        id=model.id,
        target_type=CommentTarget(model.target_type),
        target_id=model.target_id,
        author_id=model.author_id,
        body=Body(model.body),
        created_at=model.created_at,
        parent_id=model.parent_id,
    )


class SqlAlchemyCommentRepository:
    """CommentRepository 端口的 SQLAlchemy 实现（迭代 3，US-C01 / F14）。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, comment: Comment) -> None:
        self._session.add(
            CommentModel(
                id=comment.id,
                body=comment.body.value,
                target_type=comment.target_type.value,
                target_id=comment.target_id,
                author_id=comment.author_id,
                parent_id=comment.parent_id,
                created_at=comment.created_at,
            )
        )
        await self._session.flush()

    async def get_by_id(self, comment_id: UUID) -> Comment | None:
        stmt = (
            select(CommentModel)
            .where(CommentModel.id == comment_id)
            .execution_options(populate_existing=True)
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return _to_domain(model) if model is not None else None

    async def list_by_target(
        self, target_type: CommentTarget, target_id: UUID
    ) -> list[Comment]:
        stmt = (
            select(CommentModel)
            .where(
                CommentModel.target_type == target_type.value,
                CommentModel.target_id == target_id,
            )
            # 1.3 功能域 9：评论按时间正序；created_at 同刻以 id tiebreaker 定确定性全序
            .order_by(CommentModel.created_at.asc(), CommentModel.id.asc())
        )
        models = (await self._session.execute(stmt)).scalars().all()
        return [_to_domain(model) for model in models]
