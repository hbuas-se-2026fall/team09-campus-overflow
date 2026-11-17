from __future__ import annotations

from typing import Any, cast
from uuid import UUID

from sqlalchemy import ColumnElement, CursorResult, Select, exists, func, or_, select
from sqlalchemy import update as sql_update
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.qa.domain.errors import (
    AnswerAlreadyAcceptedError,
    QuestionAlreadyClosedError,
    QuestionClosedError,
)
from app.contexts.qa.domain.question import Question, QuestionStatus
from app.contexts.qa.domain.repository import QuestionFilter, QuestionSort
from app.contexts.qa.domain.tag import Tag
from app.contexts.qa.domain.value_objects import Body, Title
from app.contexts.qa.domain.vote import VoteTarget
from app.contexts.qa.infrastructure.models import (
    QuestionModel,
    QuestionTagModel,
    TagModel,
    VoteModel,
)
from app.contexts.qa.infrastructure.sql_expressions import escape_like, net_votes_expr


def _question_net_votes() -> ColumnElement[int]:
    """问题净票数相关子查询（列表 votes 排序用，v3 裁定 #4）。"""
    return (
        select(net_votes_expr())
        .where(
            VoteModel.target_type == VoteTarget.QUESTION.value,
            VoteModel.target_id == QuestionModel.id,
        )
        .correlate(QuestionModel)
        .scalar_subquery()
    )


def _rebuild_question(model: QuestionModel, tags: list[Tag]) -> Question:
    """行 → 聚合重建（get_by_id / list_paginated / list_related 共用单一路径）。"""
    return Question(
        id=model.id,
        title=Title(model.title),
        body=Body(model.body),
        author_id=model.author_id,
        created_at=model.created_at,
        accepted_answer_id=model.accepted_answer_id,
        status=QuestionStatus(model.status),
        tags=tags,
    )


def _apply_filters(
    stmt: Select[Any], filters: QuestionFilter | None
) -> Select[Any]:
    """套用 F01 筛选谓词（COUNT 与当前页共用同一份条件，保证 total 同口径）。

    多标签为 AND：去重后的每个 key 一个独立 EXISTS；同一 key 重复传参只算一次。
    """
    if filters is None:
        return stmt
    conditions: list[ColumnElement[bool]] = []
    if filters.status is not None:
        conditions.append(QuestionModel.status == filters.status.value)
    if filters.created_from is not None:
        conditions.append(QuestionModel.created_at >= filters.created_from)
    if filters.created_to is not None:
        conditions.append(QuestionModel.created_at <= filters.created_to)
    if filters.q is not None:
        # F02：标题 + 正文单条件 OR——同一行双命中仍只返回一次，不需要 DISTINCT；
        # 通配符经 escape_like 字面转义，escape 参数与转义符成对（"\\" 即单个反斜杠）
        term = f"%{escape_like(filters.q)}%"
        conditions.append(
            or_(
                QuestionModel.title.ilike(term, escape="\\"),
                QuestionModel.body.ilike(term, escape="\\"),
            )
        )
    for key in filters.tag_keys:
        conditions.append(
            exists(
                select(1)
                .select_from(QuestionTagModel)
                .join(TagModel, TagModel.id == QuestionTagModel.tag_id)
                .where(
                    QuestionTagModel.question_id == QuestionModel.id,
                    TagModel.key == key,
                )
            )
        )
    return stmt.where(*conditions)


class SqlAlchemyQuestionRepository:
    """QuestionRepository 端口的 SQLAlchemy 实现。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, question: Question) -> None:
        self._session.add(
            QuestionModel(
                id=question.id,
                title=question.title.value,
                body=question.body.value,
                author_id=question.author_id,
                created_at=question.created_at,
                accepted_answer_id=question.accepted_answer_id,
                status=question.status.value,
            )
        )
        await self._session.flush()
        # 打标关联（迭代 4）：tag 行已由目录 get-or-create 落库，此处只挂多对多边
        for tag in question.tags:
            if tag.id is not None:
                self._session.add(QuestionTagModel(question_id=question.id, tag_id=tag.id))
        await self._session.flush()

    async def update(self, question: Question) -> None:
        """可变态条件更新（迭代 5 起并发安全，参照采纳条件 UPDATE 先例）：

        - 关闭动作（实体 status=closed）：`WHERE status<>'closed' AND accepted_answer_id IS NULL`
          ——并发重复关闭恰一路 204；并发"先采纳后关闭"竞态被库级挡下（不变式 5 兜底）
        - 编辑/采纳动作（实体 status=open）：`WHERE status<>'closed'`
          ——关闭提交后仍到达的写入转 409（全冻结库级兜底，防状态回退/越权写入）
        rowcount=0 时读最新行转译领域异常（409 语义），不泄露内部细节。
        """
        values: dict[str, Any]
        conditions: list[ColumnElement[bool]] = [
            QuestionModel.status != QuestionStatus.CLOSED.value
        ]
        if question.status is QuestionStatus.CLOSED:
            # 关闭动作只写状态列：不触碰 title/body/accepted，减少与在途编辑/采纳
            # 已提交写入互相覆盖的丢失更新面；并加"未采纳"库级守卫（不变式 5）
            values = {"status": QuestionStatus.CLOSED.value}
            conditions.append(QuestionModel.accepted_answer_id.is_(None))
        else:
            # 编辑/采纳动作（status=open）：同步内容与采纳引用；已关闭行被 WHERE 挡下
            values = {
                "title": question.title.value,
                "body": question.body.value,
                "accepted_answer_id": question.accepted_answer_id,
            }
        stmt = (
            sql_update(QuestionModel)
            .where(QuestionModel.id == question.id, *conditions)
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        result = cast(CursorResult[Any], await self._session.execute(stmt))
        if result.rowcount > 0:
            return
        latest = (
            await self._session.execute(
                select(QuestionModel.status, QuestionModel.accepted_answer_id).where(
                    QuestionModel.id == question.id
                )
            )
        ).first()
        accepted = latest[1] if latest is not None else None
        if question.status is QuestionStatus.CLOSED:
            if accepted is not None:
                raise AnswerAlreadyAcceptedError("该问题已有采纳答案，不可关闭（并发兜底）")
            raise QuestionAlreadyClosedError("问题已关闭（并发兜底）")
        # open 意图写入撞上已关闭行（编辑/采纳与关闭竞态）
        raise QuestionClosedError("已关闭的问题不可更新（并发兜底）")

    async def _tags_for(self, question_ids: list[UUID]) -> dict[UUID, list[Tag]]:
        """批量装配问题标签（列表/详情共用；一次 JOIN 防 N+1）。

        显示序 = 规范码点序（Python 排序，locale 无关；PG collation 与码点序
        对中文可能分歧，故不在 SQL 侧 order_by name——与 ListTagsUseCase 同口径）。
        """
        if not question_ids:
            return {}
        stmt = (
            select(QuestionTagModel.question_id, TagModel.id, TagModel.name)
            .join(TagModel, TagModel.id == QuestionTagModel.tag_id)
            .where(QuestionTagModel.question_id.in_(question_ids))
        )
        result: dict[UUID, list[Tag]] = {qid: [] for qid in question_ids}
        for qid, tag_id, name in (await self._session.execute(stmt)).all():
            result[qid].append(Tag(value=name, id=tag_id))
        for tags in result.values():
            tags.sort(key=lambda t: t.value)
        return result

    async def get_by_id(
        self, question_id: UUID, *, for_update: bool = False
    ) -> Question | None:
        stmt = select(QuestionModel).where(QuestionModel.id == question_id)
        if for_update:
            # 写路径（悬赏/关闭/采纳）行锁串行化；populate_existing 避免读到同会话旧快照
            stmt = stmt.with_for_update().execution_options(populate_existing=True)
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return None
        # 重建聚合：历史事件不从库回放（与 identity _to_domain 同模式）
        tags_map = await self._tags_for([question_id])
        return _rebuild_question(model, tags_map[question_id])

    async def list_related(self, question_id: UUID, limit: int) -> list[Question]:
        """F03：标签共现相关推荐（单条聚合 SQL + 一次批量标签装配，无 N+1）。

        先取种子题标签键集；无标签直接短路返回空。主查询按重合数聚合，
        排序 tiebreak 全序：重合数 → 净票 → created_at → id（D3：不过滤关闭态）。
        """
        seed_keys = (
            (
                await self._session.execute(
                    select(TagModel.key)
                    .join(QuestionTagModel, QuestionTagModel.tag_id == TagModel.id)
                    .where(QuestionTagModel.question_id == question_id)
                )
            )
            .scalars()
            .all()
        )
        if not seed_keys:
            return []
        overlap = func.count(func.distinct(TagModel.key))
        stmt = (
            select(QuestionModel)
            .join(QuestionTagModel, QuestionTagModel.question_id == QuestionModel.id)
            .join(TagModel, TagModel.id == QuestionTagModel.tag_id)
            .where(
                TagModel.key.in_(seed_keys),
                QuestionModel.id != question_id,
            )
            .group_by(QuestionModel.id)
            .order_by(
                overlap.desc(),
                _question_net_votes().desc(),
                QuestionModel.created_at.desc(),
                QuestionModel.id.desc(),
            )
            .limit(limit)
        )
        models = (await self._session.execute(stmt)).scalars().all()
        tags_map = await self._tags_for([model.id for model in models])
        return [_rebuild_question(model, tags_map[model.id]) for model in models]

    async def list_paginated(
        self,
        page: int,
        page_size: int,
        sort: QuestionSort = QuestionSort.LATEST,
        filters: QuestionFilter | None = None,
    ) -> tuple[list[Question], int]:
        # 总条数与当前页同一事务快照 + 同一筛选谓词，保证分页元数据一致
        total = (
            await self._session.execute(
                _apply_filters(select(func.count()).select_from(QuestionModel), filters)
            )
        ).scalar_one()
        if sort is QuestionSort.VOTES:
            # v3 裁定 #4：净票数高→低；created_at/id 作确定性 tiebreaker 保证跨页稳定
            net = _question_net_votes()
            order_by: tuple[ColumnElement[Any], ...] = (
                net.desc(),
                QuestionModel.created_at.desc(),
                QuestionModel.id.desc(),
            )
        else:
            # created_at 同微秒并发发帖（Q-12 连发 50 帖场景）顺序不定，
            # id 作 tiebreaker 保证确定性全序，跨页不重复/不漏项
            order_by = (QuestionModel.created_at.desc(), QuestionModel.id.desc())
        stmt = (
            _apply_filters(select(QuestionModel), filters)
            .order_by(*order_by)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        models = (await self._session.execute(stmt)).scalars().all()
        tags_map = await self._tags_for([model.id for model in models])
        return (
            [_rebuild_question(model, tags_map[model.id]) for model in models],
            total,
        )
