"""教师悬赏路由（F07）：发起（仅教师）+ 查询进行中悬赏（公开）。"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app.contexts.identity.interfaces.api.deps import CurrentUser
from app.contexts.qa.application.commands import CreateBountyCommand
from app.contexts.qa.application.create_bounty_use_case import CreateBountyUseCase
from app.contexts.qa.application.get_bounty_use_case import GetBountyUseCase
from app.contexts.qa.domain.bounty import Bounty
from app.contexts.qa.interfaces.api.deps import (
    BountyRepo,
    BountyServiceDep,
    QuestionRepo,
)
from app.contexts.qa.interfaces.api.schemas import BountyCreateRequest, BountyResponse

bounty_router = APIRouter(prefix="/api/v1/questions", tags=["bounty"])


def _response(bounty: Bounty) -> BountyResponse:
    return BountyResponse(
        id=bounty.id,
        question_id=bounty.question_id,
        teacher_id=bounty.teacher_id,
        amount=bounty.amount,
        status=bounty.status.value,
        created_at=bounty.created_at,
        settled_at=bounty.settled_at,
    )


@bounty_router.post(
    "/{question_id}/bounty",
    response_model=BountyResponse,
    status_code=status.HTTP_201_CREATED,
    summary="发起教师悬赏（仅教师；F07；余额不足/已有悬赏 409）",
)
async def create_bounty(
    question_id: UUID,
    payload: BountyCreateRequest,
    user: CurrentUser,
    questions: QuestionRepo,
    bounty_service: BountyServiceDep,
) -> BountyResponse:
    if user.role != "teacher":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="仅教师可发起悬赏"
        )
    bounty = await CreateBountyUseCase(questions, bounty_service).execute(
        CreateBountyCommand(
            question_id=question_id,
            teacher_id=user.id,  # 教师只取令牌，绝不取自请求体
            amount=payload.amount,
        )
    )
    return _response(bounty)


@bounty_router.get(
    "/{question_id}/bounty",
    response_model=BountyResponse | None,
    summary="查询进行中的教师悬赏（公开；无悬赏返回 null）",
)
async def get_bounty(
    question_id: UUID,
    questions: QuestionRepo,
    bounties: BountyRepo,
) -> BountyResponse | None:
    if await questions.get_by_id(question_id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="问题不存在"
        )
    bounty = await GetBountyUseCase(bounties).execute(question_id)
    return None if bounty is None else _response(bounty)
