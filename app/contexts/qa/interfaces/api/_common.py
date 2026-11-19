"""qa 路由共用助手（跨 questions / answers 两个 router 使用）。

私有模块：仅 qa interfaces 包内消费，不对外暴露。
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Response, status

from app.contexts.identity.application.ports import (
    UserSummary,
    pick_summary_display_name,
)
from app.contexts.qa.application.commands import CreateCommentCommand, VoteOnCommand
from app.contexts.qa.application.comment_use_case import CreateCommentUseCase
from app.contexts.qa.application.vote_use_case import VoteOnUseCase
from app.contexts.qa.domain.comment import Comment, CommentTarget
from app.contexts.qa.domain.vote import VoteCast, VoteDirection, VoteTarget
from app.contexts.qa.interfaces.api.deps import (
    AnswerRepo,
    CommentRepo,
    NotificationWriterDep,
    QuestionRepo,
    VoteRepo,
)
from app.contexts.qa.interfaces.api.schemas import (
    CommentRequest,
    CommentResponse,
    VoteRequest,
)
from app.contexts.reputation.application.ports import VoteEventPayload
from app.contexts.reputation.interfaces.publisher import EventPublisherDep


async def vote_on_target(
    target_type: VoteTarget,
    target_id: UUID,
    payload: VoteRequest,
    user_id: UUID,
    questions: QuestionRepo,
    answers: AnswerRepo,
    votes: VoteRepo,
    publisher: EventPublisherDep,
) -> Response:
    """两个投票端点共用：成功 204；目标不存在 404；重复票（含改票）409。

    成功后经声誉发布端口投递 VoteCast（延迟门面：scope="function" 下 commit
    先于响应发送，实际 .delay 在响应后执行——发布时序探针 R-07 实证，ADR-004）。
    """
    use_case = VoteOnUseCase(questions, answers, votes)
    result = await use_case.execute(
        VoteOnCommand(
            target_type=target_type,
            target_id=target_id,
            direction=VoteDirection(payload.direction),
            user_id=user_id,
        )
    )
    publisher.publish_vote(vote_event_payload(result.event))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def vote_event_payload(event: VoteCast) -> VoteEventPayload:
    """qa 领域事件 → reputation 已发布语言 DTO（字段映射，不做序列化）。"""
    return VoteEventPayload(
        vote_id=event.vote_id,
        user_id=event.user_id,
        target_type=event.target_type.value,
        target_id=event.target_id,
        direction=event.direction.value,
        target_author_id=event.target_author_id,
        occurred_at=event.occurred_at,
    )


async def create_comment_on_target(
    target_type: CommentTarget,
    target_id: UUID,
    payload: CommentRequest,
    user_id: UUID,
    author_name: str,
    questions: QuestionRepo,
    answers: AnswerRepo,
    comments: CommentRepo,
    notification_writer: NotificationWriterDep,
) -> CommentResponse:
    """题评/答评端点共用：成功 201 + 白名单；目标不存在 404；正文兜底 422。"""
    use_case = CreateCommentUseCase(questions, answers, comments, notification_writer)
    comment = await use_case.execute(
        CreateCommentCommand(
            target_type=target_type,
            target_id=target_id,
            body=payload.body,
            author_id=user_id,  # 作者只取令牌，绝不取自请求体
        )
    )
    return comment_response(comment, author_name=author_name)


def comment_response(comment: Comment, *, author_name: str) -> CommentResponse:
    return CommentResponse(
        id=comment.id,
        body=comment.body.value,
        author_id=comment.author_id,
        author_name=author_name,
        created_at=comment.created_at,
    )


def display_name_for(summaries: dict[UUID, UserSummary], user_id: UUID) -> str:
    """从批量摘要字典取展示名；缺失用户安全降级，绝不因孤立引用报错。"""
    return pick_summary_display_name(summaries, user_id)
