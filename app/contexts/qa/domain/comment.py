from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from app.contexts.qa.domain.value_objects import Body
from app.shared.errors import DomainValidationError


class CommentTarget(StrEnum):
    """评论目标类型：题评挂 Question、答评挂 Answer（aggregates.md L17）。

    与 VoteTarget 值域相同但语义独立，各聚合各自持有，不跨模块耦合。
    """

    QUESTION = "question"
    ANSWER = "answer"


@dataclass(frozen=True, slots=True)
class CommentCreated:
    """领域事件：评论发布完成（US-C01 / F14）。

    迭代 3 无订阅者；照聚合规范照发，为事件总线留位。
    """

    comment_id: UUID
    target_type: CommentTarget
    target_id: UUID
    author_id: UUID
    occurred_at: datetime
    parent_id: UUID | None = None


@dataclass
class Comment:
    """评论实体（aggregates.md L17：题评归属 Question 聚合、答评归属 Answer 聚合）。

    建模与 Vote 同模式：独立仓储 + 多态 target（target_type + target_id），
    避免第三聚合；生命周期跟随宿主。
    正文复用 Body 值对象（1~5000 字，strip 规范化）——v3 自裁：1.3 未单独定义评论长度。
    F14 支持严格二级回复：一级评论 parent_id 为 None，二级回复指向同一宿主下的一级评论。
    """

    id: UUID
    target_type: CommentTarget
    target_id: UUID
    author_id: UUID
    body: Body
    created_at: datetime
    parent_id: UUID | None = None
    events: list[CommentCreated] = field(default_factory=list, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.parent_id is not None and self.parent_id == self.id:
            raise DomainValidationError("评论不能回复自身")

    @staticmethod
    def validate_parent(
        parent: Comment,
        *,
        target_type: CommentTarget,
        target_id: UUID,
    ) -> None:
        """校验父评论归属与层级上限（F14 D2）。

        1. 父评论必须与当前请求属于同一 (target_type, target_id) 宿主；
        2. 仅支持二级回复，不可回复自身已有 parent_id 的二级评论。
        """
        if parent.target_type != target_type or parent.target_id != target_id:
            raise DomainValidationError("父评论不属于当前对象")
        if parent.parent_id is not None:
            raise DomainValidationError("评论仅支持二级回复，不可回复二级评论")

    @classmethod
    def write(
        cls,
        *,
        target_type: CommentTarget,
        target_id: UUID,
        author_id: UUID,
        body_value: str,
        parent: Comment | None = None,
    ) -> Comment:
        """工厂：发表评论或二级回复。Body 值对象与父评论不变式即校验，并发布 CommentCreated。"""
        target = CommentTarget(target_type)
        parent_id: UUID | None = None
        if parent is not None:
            cls.validate_parent(parent, target_type=target, target_id=target_id)
            parent_id = parent.id
        now = datetime.now(UTC)
        comment = cls(
            id=uuid4(),
            target_type=target,
            target_id=target_id,
            author_id=author_id,
            body=Body(body_value),
            created_at=now,
            parent_id=parent_id,
        )
        comment.events.append(
            CommentCreated(
                comment_id=comment.id,
                target_type=target,
                target_id=target_id,
                author_id=author_id,
                occurred_at=now,
                parent_id=parent_id,
            )
        )
        return comment

