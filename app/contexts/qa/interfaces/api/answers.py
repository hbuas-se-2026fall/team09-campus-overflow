"""回答路由：答评/采纳（回答票因路径嵌套挂在 questions 路由）。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Response, status

from app.contexts.identity.interfaces.api.deps import (
    AnswerVerifierUser,
    CurrentUser,
    UserSummaryReaderDep,
)
from app.contexts.qa.application.accept_use_case import AcceptAnswerUseCase
from app.contexts.qa.application.commands import (
    AcceptAnswerCommand,
    DeleteAnswerCommand,
    EditAnswerCommand,
    UnverifyAnswerCommand,
    VerifyAnswerCommand,
)
from app.contexts.qa.application.delete_answer_use_case import DeleteAnswerUseCase
from app.contexts.qa.application.edit_answer_use_case import EditAnswerUseCase
from app.contexts.qa.application.verify_answer_use_case import (
    UnverifyAnswerUseCase,
    VerifyAnswerUseCase,
)
from app.contexts.qa.domain.answer import AnswerAccepted
from app.contexts.qa.domain.comment import CommentTarget
from app.contexts.qa.interfaces.api._common import (
    create_comment_on_target,
    hydrate_answer_response,
)
from app.contexts.qa.interfaces.api.deps import (
    AnswerRepo,
    BountyServiceDep,
    CommentRepo,
    NotificationWriterDep,
    QuestionRepo,
)
from app.contexts.qa.interfaces.api.schemas import (
    AnswerResponse,
    CommentRequest,
    CommentResponse,
    EditAnswerRequest,
)
from app.contexts.reputation.application.ports import AcceptEventPayload
from app.contexts.reputation.interfaces.publisher import EventPublisherDep

answers_router = APIRouter(prefix="/api/v1/answers", tags=["answers"])


@answers_router.patch(
    "/{answer_id}",
    response_model=AnswerResponse,
    summary="编辑回答（仅回答者，US-A02 / F12；已关闭问题 409）",
)
async def edit_answer(
    answer_id: UUID,
    payload: EditAnswerRequest,
    user: CurrentUser,
    questions: QuestionRepo,
    answers: AnswerRepo,
    comments: CommentRepo,
    summary_reader: UserSummaryReaderDep,
) -> AnswerResponse:
    answer = await EditAnswerUseCase(questions, answers).execute(
        EditAnswerCommand(
            answer_id=answer_id,
            actor_id=user.id,
            body=payload.body,
        )
    )
    return await hydrate_answer_response(
        answer,
        comments=comments,
        summary_reader=summary_reader,
        known_author_name=user.display_name,
    )


@answers_router.post(
    "/{answer_id}/verify",
    response_model=AnswerResponse,
    summary="教师/助教/管理员认证回答（F15；幂等 200；学生 403 / 关闭问题 409）",
)
async def verify_answer(
    answer_id: UUID,
    user: AnswerVerifierUser,
    questions: QuestionRepo,
    answers: AnswerRepo,
    comments: CommentRepo,
    notification_writer: NotificationWriterDep,
    summary_reader: UserSummaryReaderDep,
) -> AnswerResponse:
    answer = await VerifyAnswerUseCase(
        questions, answers, notification_writer
    ).execute(VerifyAnswerCommand(answer_id=answer_id, actor_id=user.id))
    return await hydrate_answer_response(
        answer,
        comments=comments,
        summary_reader=summary_reader,
    )


@answers_router.delete(
    "/{answer_id}/verify",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="教师/助教/管理员取消回答认证（F15；幂等 204；学生 403 / 关闭问题 409）",
)
async def unverify_answer(
    answer_id: UUID,
    _user: AnswerVerifierUser,
    questions: QuestionRepo,
    answers: AnswerRepo,
) -> Response:
    await UnverifyAnswerUseCase(questions, answers).execute(
        UnverifyAnswerCommand(answer_id=answer_id)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@answers_router.delete(
    "/{answer_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="软删除回答（仅回答者；父问题活跃时作者重复删幂等 204；已采纳 409）",
)
async def delete_answer(
    answer_id: UUID,
    user: CurrentUser,
    questions: QuestionRepo,
    answers: AnswerRepo,
) -> Response:
    await DeleteAnswerUseCase(questions, answers).execute(
        DeleteAnswerCommand(answer_id=answer_id, actor_id=user.id)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@answers_router.post(
    "/{answer_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="对回答发表评论或二级回复（登录用户，US-C01 / F14）",
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
        user.display_name,
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
