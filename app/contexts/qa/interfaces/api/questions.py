"""问题路由：提问/列表/详情/编辑/关闭/回答/问题票/题评。"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.contexts.identity.interfaces.api.deps import (
    CurrentUser,
    UserSummaryReaderDep,
)
from app.contexts.qa.application.answer_use_case import PostAnswerUseCase
from app.contexts.qa.application.ask_question_use_case import AskQuestionUseCase
from app.contexts.qa.application.close_question_use_case import CloseQuestionUseCase
from app.contexts.qa.application.commands import (
    AskQuestionCommand,
    CloseQuestionCommand,
    DeleteQuestionCommand,
    EditQuestionCommand,
    PostAnswerCommand,
)
from app.contexts.qa.application.delete_question_use_case import DeleteQuestionUseCase
from app.contexts.qa.application.edit_question_use_case import EditQuestionUseCase
from app.contexts.qa.application.get_question_use_case import GetQuestionUseCase
from app.contexts.qa.application.list_questions_use_case import ListQuestionsUseCase
from app.contexts.qa.application.list_related_questions_use_case import (
    ListRelatedQuestionsUseCase,
)
from app.contexts.qa.application.queries import (
    GetQuestionQuery,
    ListQuestionsQuery,
    ListRelatedQuestionsQuery,
)
from app.contexts.qa.domain.comment import CommentTarget
from app.contexts.qa.domain.question import Question, QuestionStatus
from app.contexts.qa.domain.repository import QuestionFilter, QuestionSort
from app.contexts.qa.domain.vote import VoteTarget
from app.contexts.qa.interfaces.api._common import (
    comment_response,
    create_comment_on_target,
    display_name_for,
    vote_on_target,
)
from app.contexts.qa.interfaces.api.deps import (
    AnswerRepo,
    BountyServiceDep,
    CommentRepo,
    NotificationWriterDep,
    QuestionRepo,
    TagCatalogRepo,
    VoteRepo,
)
from app.contexts.qa.interfaces.api.schemas import (
    AnswerResponse,
    AskQuestionRequest,
    CommentRequest,
    CommentResponse,
    EditQuestionRequest,
    PostAnswerRequest,
    QuestionDetailResponse,
    QuestionListItem,
    QuestionListResponse,
    QuestionResponse,
    VoteRequest,
)
from app.contexts.reputation.interfaces.publisher import EventPublisherDep

router = APIRouter(prefix="/api/v1/questions", tags=["questions"])


@router.post(
    "",
    response_model=QuestionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="发布问题（登录用户）",
)
async def ask_question(
    payload: AskQuestionRequest,
    user: CurrentUser,
    questions: QuestionRepo,
    tags: TagCatalogRepo,
) -> QuestionResponse:
    use_case = AskQuestionUseCase(questions, tags)
    question = await use_case.execute(
        AskQuestionCommand(
            title=payload.title,
            body=payload.body,
            author_id=user.id,  # 作者只取令牌中的当前用户，绝不取自请求体
            tags=tuple(payload.tags),
        )
    )
    return _question_response(question, author_name=user.display_name)


@router.get(
    "",
    response_model=QuestionListResponse,
    summary="问题列表（访客可用；可按关键词/标签/状态/创建时间筛选，默认按发布时间新→旧）",
)
async def list_questions(
    questions: QuestionRepo,
    summary_reader: UserSummaryReaderDep,
    page: int = Query(default=1, ge=1, description="页码，从 1 起"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数，上限 100（S-05）"),
    sort: QuestionSort = Query(
        default=QuestionSort.LATEST,
        description="排序：latest=最新（默认）；votes=净票数高→低（US-Q02 迭代 2）",
    ),
    q: str | None = Query(
        default=None,
        description=(
            "按标题与正文模糊搜索，大小写不敏感（F02）；空串/纯空白等价于不传，"
            "至多 100 字（超限 422），% _ \\ 按字面匹配"
        ),
    ),
    tag: list[str] | None = Query(
        default=None,
        description=(
            "按标签筛选，可重复传参（?tag=a&tag=b）；多个标签为 AND，大小写不敏感；"
            "去重后至多 5 个（与每题标签上限一致，超限 422）"
        ),
    ),
    status_filter: QuestionStatus | None = Query(
        default=None,
        alias="status",
        description="按状态筛选：open / closed；不传=全部（F01）",
    ),
    created_from: datetime | None = Query(
        default=None, description="创建时间下界（闭区间，须带时区；F01）"
    ),
    created_to: datetime | None = Query(
        default=None, description="创建时间上界（闭区间，须带时区；F01）"
    ),
) -> QuestionListResponse:
    # sort/status 为枚举：非法值（含注入串）在参数校验即 422，不进 SQL（S-07）
    # 逆序/无时区/tag 非法字符/q 超长或控制字符由 QuestionFilter.__post_init__
    # 抛 DomainValidationError，经全局映射落 422；路由不新增 try/except（C2 收口口径）
    filters = QuestionFilter(
        tags=tuple(tag or ()),
        status=status_filter,
        created_from=created_from,
        created_to=created_to,
        q=q,
    )
    use_case = ListQuestionsUseCase(questions)
    result = await use_case.execute(
        ListQuestionsQuery(page=page, page_size=page_size, sort=sort, filters=filters)
    )
    summaries = await summary_reader.get_summaries(q.author_id for q in result.items)
    return QuestionListResponse(
        items=[
            QuestionListItem(
                id=q.id,
                title=q.title.value,
                author_id=q.author_id,
                author_name=display_name_for(summaries, q.author_id),
                created_at=q.created_at,
                tags=[t.value for t in q.tags],
                status=q.status,
            )
            for q in result.items
        ],
        total=result.total,
        page=result.page,
        page_size=result.page_size,
        total_pages=result.total_pages,
    )


@router.get(
    "/{question_id}",
    response_model=QuestionDetailResponse,
    summary="问题详情（访客可用，answers 按 D2 排序）",
)
async def get_question(
    question_id: UUID,
    questions: QuestionRepo,
    answers: AnswerRepo,
    comments: CommentRepo,
    summary_reader: UserSummaryReaderDep,
) -> QuestionDetailResponse:
    use_case = GetQuestionUseCase(questions, answers, comments)
    view = await use_case.execute(GetQuestionQuery(question_id=question_id))
    if view is None:
        # S-10：只回业务语义，不泄露内部信息
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="问题不存在")
    # 合并题主 + 回答 + 题评 + 答评的全部 author_id，单次 IN 查询杜绝 N+1
    author_ids: list[UUID] = [view.question.author_id]
    author_ids.extend(a.author_id for a in view.answers)
    author_ids.extend(c.author_id for c in view.question_comments)
    for comments_list in view.answer_comments.values():
        author_ids.extend(c.author_id for c in comments_list)
    summaries = await summary_reader.get_summaries(author_ids)
    return QuestionDetailResponse(
        id=view.question.id,
        title=view.question.title.value,
        body=view.question.body.value,
        author_id=view.question.author_id,
        author_name=display_name_for(summaries, view.question.author_id),
        created_at=view.question.created_at,
        accepted_answer_id=view.question.accepted_answer_id,
        tags=[t.value for t in view.question.tags],
        status=view.question.status,
        answers=[
            AnswerResponse(
                id=a.id,
                body=a.body.value,
                author_id=a.author_id,
                author_name=display_name_for(summaries, a.author_id),
                created_at=a.created_at,
                votes=a.votes_count,
                is_accepted=a.is_accepted,
                comments=[
                    comment_response(c, author_name=display_name_for(summaries, c.author_id))
                    for c in view.answer_comments.get(str(a.id), [])
                ],
            )
            for a in view.answers
        ],
        comments=[
            comment_response(c, author_name=display_name_for(summaries, c.author_id))
            for c in view.question_comments
        ],
    )


@router.get(
    "/{question_id}/related",
    response_model=list[QuestionListItem],
    summary="相关问题推荐（按标签共现；访客可用，D3 不过滤关闭态）",
)
async def list_related_questions(
    question_id: UUID,
    questions: QuestionRepo,
    summary_reader: UserSummaryReaderDep,
    limit: int = Query(default=5, ge=1, le=10, description="返回条数，1~10"),
) -> list[QuestionListItem]:
    use_case = ListRelatedQuestionsUseCase(questions)
    items = await use_case.execute(
        ListRelatedQuestionsQuery(question_id=question_id, limit=limit)
    )
    if items is None:
        # 与详情同语义：不泄露内部信息
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="问题不存在")
    summaries = await summary_reader.get_summaries(q.author_id for q in items)
    return [
        QuestionListItem(
            id=q.id,
            title=q.title.value,
            author_id=q.author_id,
            author_name=display_name_for(summaries, q.author_id),
            created_at=q.created_at,
            tags=[t.value for t in q.tags],
            status=q.status,
        )
        for q in items
    ]


@router.patch(
    "/{question_id}",
    response_model=QuestionResponse,
    summary="编辑问题（仅提问者，US-Q08；仅标题+正文；已关闭 409）",
)
async def edit_question(
    question_id: UUID,
    payload: EditQuestionRequest,
    user: CurrentUser,
    questions: QuestionRepo,
) -> QuestionResponse:
    use_case = EditQuestionUseCase(questions)
    question = await use_case.execute(
        EditQuestionCommand(
            question_id=question_id,
            actor_id=user.id,
            title=payload.title,
            body=payload.body,
        )
    )
    return _question_response(question, author_name=user.display_name)


def _question_response(question: Question, *, author_name: str) -> QuestionResponse:
    """问题白名单响应唯一装配处（创建/编辑复用，tags 统一码点序）。"""
    return QuestionResponse(
        id=question.id,
        title=question.title.value,
        body=question.body.value,
        author_id=question.author_id,
        author_name=author_name,
        created_at=question.created_at,
        tags=sorted(t.value for t in question.tags),
        status=question.status,
    )


@router.post(
    "/{question_id}/close",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="关闭问题（仅提问者，US-Q08；重复关闭/已采纳 409）",
)
async def close_question(
    question_id: UUID,
    user: CurrentUser,
    questions: QuestionRepo,
    bounty_service: BountyServiceDep,
) -> Response:
    use_case = CloseQuestionUseCase(questions, bounty_service)
    await use_case.execute(CloseQuestionCommand(question_id=question_id, actor_id=user.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{question_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="软删除问题（仅提问者；作者重复删幂等 204；已采纳 409；联动退还开放悬赏）",
)
async def delete_question(
    question_id: UUID,
    user: CurrentUser,
    questions: QuestionRepo,
    bounty_service: BountyServiceDep,
) -> Response:
    await DeleteQuestionUseCase(questions, bounty_service).execute(
        DeleteQuestionCommand(question_id=question_id, actor_id=user.id)
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{question_id}/answers",
    response_model=AnswerResponse,
    status_code=status.HTTP_201_CREATED,
    summary="发布回答（登录用户，US-A01）",
)
async def post_answer(
    question_id: UUID,
    payload: PostAnswerRequest,
    user: CurrentUser,
    questions: QuestionRepo,
    answers: AnswerRepo,
    notification_writer: NotificationWriterDep,
) -> AnswerResponse:
    use_case = PostAnswerUseCase(questions, answers, notification_writer)
    answer = await use_case.execute(
        PostAnswerCommand(
            question_id=question_id,
            body=payload.body,
            author_id=user.id,  # 作者只取令牌，绝不取自请求体
        )
    )

    return AnswerResponse(
        id=answer.id,
        body=answer.body.value,
        author_id=answer.author_id,
        author_name=user.display_name,
        created_at=answer.created_at,
        votes=0,  # 新回答无票
        is_accepted=answer.is_accepted,
    )


@router.post(
    "/{question_id}/vote",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="对问题投票（登录用户，US-V01；重复票/改票 409）",
)
async def vote_question(
    question_id: UUID,
    payload: VoteRequest,
    user: CurrentUser,
    questions: QuestionRepo,
    answers: AnswerRepo,
    votes: VoteRepo,
    publisher: EventPublisherDep,
) -> Response:
    return await vote_on_target(
        VoteTarget.QUESTION,
        question_id,
        payload,
        user.id,
        questions,
        answers,
        votes,
        publisher,
    )


@router.post(
    "/{question_id}/answers/{answer_id}/vote",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="对回答投票（登录用户，US-V01；重复票/改票 409）",
)
async def vote_answer(
    question_id: UUID,
    answer_id: UUID,
    payload: VoteRequest,
    user: CurrentUser,
    questions: QuestionRepo,
    answers: AnswerRepo,
    votes: VoteRepo,
    publisher: EventPublisherDep,
) -> Response:
    # 路径嵌套仅为可读性；回答存在性由 answer_id 定位（question_id 不参与查询）
    return await vote_on_target(
        VoteTarget.ANSWER,
        answer_id,
        payload,
        user.id,
        questions,
        answers,
        votes,
        publisher,
    )


@router.post(
    "/{question_id}/comments",
    response_model=CommentResponse,
    status_code=status.HTTP_201_CREATED,
    summary="对问题发表评论（登录用户，US-C01）",
)
async def comment_question(
    question_id: UUID,
    payload: CommentRequest,
    user: CurrentUser,
    questions: QuestionRepo,
    answers: AnswerRepo,
    comments: CommentRepo,
    notification_writer: NotificationWriterDep,
) -> CommentResponse:
    return await create_comment_on_target(
        CommentTarget.QUESTION,
        question_id,
        payload,
        user.id,
        user.display_name,
        questions,
        answers,
        comments,
        notification_writer,
    )
