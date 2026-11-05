"""qa 组合根：仓储适配器的唯一装配处。

interfaces 层只在本文件 import infrastructure；路由拿到的参数类型是 domain
端口（Protocol）。换存储实现只改本文件，路由也可用假仓储直接单测。

会话依赖统一在此声明 `scope="function"`：get_session 的退出代码（commit）
须在响应发送前执行（ADR-003）；同一请求内多个仓储依赖共享同一个会话实例
（FastAPI 依赖缓存命中同一 get_session）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.contexts.qa.domain.repository import (
    AnswerRepository,
    CommentRepository,
    QuestionRepository,
    TagCatalogRepository,
    VoteRepository,
)
from app.contexts.qa.infrastructure.repository import (
    SqlAlchemyAnswerRepository,
    SqlAlchemyCommentRepository,
    SqlAlchemyQuestionRepository,
    SqlAlchemyTagCatalogRepository,
    SqlAlchemyVoteRepository,
)
from app.platform.http.deps import SessionDep


def get_question_repository(session: SessionDep) -> QuestionRepository:
    return SqlAlchemyQuestionRepository(session)


def get_answer_repository(session: SessionDep) -> AnswerRepository:
    return SqlAlchemyAnswerRepository(session)


def get_vote_repository(session: SessionDep) -> VoteRepository:
    return SqlAlchemyVoteRepository(session)


def get_comment_repository(session: SessionDep) -> CommentRepository:
    return SqlAlchemyCommentRepository(session)


def get_tag_catalog_repository(session: SessionDep) -> TagCatalogRepository:
    return SqlAlchemyTagCatalogRepository(session)


QuestionRepo = Annotated[QuestionRepository, Depends(get_question_repository)]
AnswerRepo = Annotated[AnswerRepository, Depends(get_answer_repository)]
VoteRepo = Annotated[VoteRepository, Depends(get_vote_repository)]
CommentRepo = Annotated[CommentRepository, Depends(get_comment_repository)]
TagCatalogRepo = Annotated[TagCatalogRepository, Depends(get_tag_catalog_repository)]
