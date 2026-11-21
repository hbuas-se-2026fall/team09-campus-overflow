"""评论用例：对问题/回答发表评论（US-C01）。"""

from __future__ import annotations

from app.contexts.qa.application.commands import CreateCommentCommand
from app.contexts.qa.application.ports import NotificationWriter
from app.contexts.qa.domain.comment import Comment, CommentTarget
from app.contexts.qa.domain.errors import (
    AnswerNotFoundError,
    QuestionNotFoundError,
)
from app.contexts.qa.domain.repository import (
    AnswerRepository,
    CommentRepository,
    QuestionRepository,
)


class CreateCommentUseCase:
    """评论用例：目标存在检查（404）→ 关闭态拦截（409，迭代 5 落地 v3 裁定 #2）
    → Comment.write（Body 即校验，422）→ 落库。

    题评挂 Question、答评挂 Answer（aggregates.md L17）；
    已关闭禁评含题评与答评（答评经 answer.question_id 回溯父问题，全冻结口径）。
    F04：同事务写"我的问题/回答有新评论"通知（宿主作者 ≠ 评论者时）。
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
        if command.target_type is CommentTarget.QUESTION:
            question = await self._question_repository.get_by_id(
                command.target_id, for_update=True
            )
            if question is None:
                raise QuestionNotFoundError("问题不存在")
            question.ensure_open("评论")
            host_author_id = question.author_id
            host_question_id = question.id
        else:
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
            host_author_id = answer.author_id
            host_question_id = answer.question_id
        comment = Comment.write(
            target_type=command.target_type,
            target_id=command.target_id,
            author_id=command.author_id,
            body_value=command.body,
        )
        await self._comment_repository.add(comment)
        if (
            self._notification_writer is not None
            and host_author_id != comment.author_id
        ):
            await self._notification_writer.write(
                recipient_id=host_author_id,
                type="comment_created",
                actor_id=comment.author_id,
                target_type=command.target_type.value,
                target_id=command.target_id,
                source_event_id=comment.id,
                question_id=host_question_id,
            )
        return comment