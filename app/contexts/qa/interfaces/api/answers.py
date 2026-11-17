"""回答路由：答评/采纳（回答票因路径嵌套挂在 questions 路由）。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response, status

from app.contexts.identity.interfaces.api.deps import CurrentUser
from app.contexts.qa.application.accept_use_case import AcceptAnswerUseCase
from app.contexts.qa.application.commands import AcceptAnswerCommand
from app.contexts.qa.domain.answer import AnswerAccepted
from app.contexts.qa.domain.comment import CommentTarget
from app.contexts.qa.interfaces.api._common import create_comment_on_target
from app.contexts.qa.interfaces.api.deps import (
    AnswerRepo,
    BountyServiceDep,
    CommentRepo,
    NotificationWriterDep,
    QuestionRepo,
)
from app.contexts.qa.interfaces.api.schemas import CommentRequest, CommentResponse
from app.contexts.reputation.application.ports import AcceptEventPayload
from app.contexts.reputation.interfaces.publisher import EventPublisherDep

answers_router = APIRouter(prefix="/api/v1/answers", tags=["answers"])


@answers_router.post(
    "/{answer_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="对回答发表评论（登录用户，US-C01）",
)
async def comment_answer(
    answer_id: UUID,
    payload: CommentRequest,
    user: CurrentUser,
    questions: QuestionRepo,
    answers: AnswerRepo,
    comments: CommentRepo,
    notification_writer: NotificationWriterDep,
) -> CommentResponse:
    return await create_comment_on_target(
        CommentTarget.ANSWER,
        answer_id,
        payload,
        user.id,
        questions,
        answers,
        comments,
        notification_writer,
    )


@answers_router.post(
    "/{answer_id}/accept",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="采纳最佳答案（仅提问者，US-V03；非提问者 403 / 重复采纳 409）",
)
async def accept_answer(
    answer_id: UUID,
    user: CurrentUser,
    questions: QuestionRepo,
    answers: AnswerRepo,
    publisher: EventPublisherDep,
    notification_writer: NotificationWriterDep,
    bounty_service: BountyServiceDep,
) -> Response:
    use_case = AcceptAnswerUseCase(
        questions, answers, notification_writer, bounty_service
    )
    result = await use_case.execute(AcceptAnswerCommand(answer_id=answer_id, actor_id=user.id))
    publisher.publish_accept(_accept_payload(result.event))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _accept_payload(event: AnswerAccepted) -> AcceptEventPayload:
    """qa 领域事件 → reputation 已发布语言 DTO。"""
    return AcceptEventPayload(
        event_id=event.event_id,
        answer_id=event.answer_id,
        answer_author_id=event.answer_author_id,
        occurred_at=event.occurred_at,
    )
