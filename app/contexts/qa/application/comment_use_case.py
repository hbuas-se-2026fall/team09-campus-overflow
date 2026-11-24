"""评论用例：对问题/回答发表评论及二级回复（US-C01 / F14）。"""

from __future__ import annotations

from uuid import UUID

from app.contexts.qa.application.commands import CreateCommentCommand
from app.contexts.qa.application.ports import NotificationWriter
from app.contexts.qa.domain.comment import Comment, CommentTarget
from app.contexts.qa.domain.errors import (
    AnswerNotFoundError,
    CommentNotFoundError,
    QuestionNotFoundError,
)
from app.contexts.qa.domain.repository import (
    AnswerRepository,
    CommentRepository,
    QuestionRepository,
)


class CreateCommentUseCase:
    """评论用例：宿主锁与状态检查（404/409）→ 父评论存在与层级检查（404/422）
    → Comment.write（Body 即校验，422）→ 落库 → 同事务通知（F04 / F14 D4）。

    单根无环锁序（沿用 F13）：
    - 题评：锁 Question(for_update=True) → 校验未删与未关闭；
    - 答评：读 Answer → 锁父 Question(for_update=True) → 锁后重读 Answer → 校验未关闭。
    """

    def __init__(
        self,
        question_repository: QuestionRepository,
        answer_repository: AnswerRepository,
        comment_repository: CommentRepository,
        notification_writer: NotificationWriter | None = None,
    ) -> None:
        self._question_repository = question_repository
        self._answer_repository = answer_repository
        self._comment_repository = comment_repository
        self._notification_writer = notification_writer

    async def execute(self, command: CreateCommentCommand) -> Comment:
        host_author_id, host_question_id = await self._resolve_host(command)
        parent_comment = await self._resolve_parent(command.parent_id)
        comment = Comment.write(
            target_type=command.target_type,
            target_id=command.target_id,
            author_id=command.author_id,
            body_value=command.body,
            parent=parent_comment,
        )
        await self._comment_repository.add(comment)
        await self._notify(comment, parent_comment, host_author_id, host_question_id)
        return comment

    async def _resolve_host(self, command: CreateCommentCommand) -> tuple[UUID, UUID]:
        """校验宿主存在/未软删除并加父问题行锁，同时拦截关闭态。"""
        if command.target_type is CommentTarget.QUESTION:
            question = await self._question_repository.get_by_id(
                command.target_id, for_update=True
            )
            if question is None:
                raise QuestionNotFoundError("问题不存在")
            question.ensure_open("评论")
            return question.author_id, question.id

        answer = await self._answer_repository.get_by_id(command.target_id)
        if answer is None:
            raise AnswerNotFoundError("回答不存在")
        # 统一锁序“先无锁读 Answer，再锁父 Question”，与关闭/采纳/编辑/删除回答一致无环
        parent = await self._question_repository.get_by_id(
            answer.question_id, for_update=True
        )
        if parent is None:
            raise QuestionNotFoundError("问题不存在")
        # 拿到父问题锁后重读 Answer，闭环并发软删回答窗口（F13 D4）
        answer = await self._answer_repository.get_by_id(command.target_id)
        if answer is None:
            raise AnswerNotFoundError("回答不存在")
        parent.ensure_open("对回答评论")
        return answer.author_id, answer.question_id

    async def _resolve_parent(self, parent_id: UUID | None) -> Comment | None:
        if parent_id is None:
            return None
        parent_comment = await self._comment_repository.get_by_id(parent_id)
        if parent_comment is None:
            raise CommentNotFoundError("评论不存在")
        return parent_comment

    async def _notify(
        self,
        comment: Comment,
        parent_comment: Comment | None,
        host_author_id: UUID,
        host_question_id: UUID,
    ) -> None:
        if self._notification_writer is None:
            return
        if parent_comment is not None and parent_comment.author_id != comment.author_id:
            await self._notification_writer.write(
                recipient_id=parent_comment.author_id,
                type="comment_replied",
                actor_id=comment.author_id,
                target_type="comment",
                target_id=parent_comment.id,
                source_event_id=comment.id,
                question_id=host_question_id,
            )
        parent_author_id = parent_comment.author_id if parent_comment is not None else None
        if host_author_id != comment.author_id and host_author_id != parent_author_id:
            await self._notification_writer.write(
                recipient_id=host_author_id,
                type="comment_created",
                actor_id=comment.author_id,
                target_type=comment.target_type.value,
                target_id=comment.target_id,
                source_event_id=comment.id,
                question_id=host_question_id,
            )