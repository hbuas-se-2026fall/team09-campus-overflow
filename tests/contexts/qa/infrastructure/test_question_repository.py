"""QuestionRepository 集成测试：真 PostgreSQL（docker compose up -d）。

questions.author_id 外键指向 users，故先经注册用例建作者。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.identity.application.commands import RegisterCommand
from app.contexts.identity.application.register_use_case import RegisterUseCase
from app.contexts.identity.infrastructure.password_hasher import BcryptPasswordHasher
from app.contexts.identity.infrastructure.repository import SqlAlchemyUserRepository
from app.contexts.qa.application.ask_question_use_case import AskQuestionUseCase
from app.contexts.qa.application.commands import AskQuestionCommand
from app.contexts.qa.domain.question import Question, QuestionStatus
from app.contexts.qa.domain.repository import QuestionFilter
from app.contexts.qa.domain.tag import Tag
from app.contexts.qa.domain.value_objects import Body, Title
from app.contexts.qa.domain.vote import Vote, VoteDirection, VoteTarget
from app.contexts.qa.infrastructure.question_repository import SqlAlchemyQuestionRepository
from app.contexts.qa.infrastructure.tag_repository import SqlAlchemyTagCatalogRepository
from app.contexts.qa.infrastructure.vote_repository import SqlAlchemyVoteRepository
from app.shared.engine import session_factory

pytestmark = pytest.mark.integration


async def _make_author() -> uuid.UUID:
    """注册一个学生用户并 commit，返回其 user.id（供 question.author_id 外键）。"""
    async with session_factory() as session:
        use_case = RegisterUseCase(SqlAlchemyUserRepository(session), BcryptPasswordHasher())
        user = await use_case.execute(
            RegisterCommand(
                role="student",
                email=f"{uuid.uuid4()}@stu.edu.cn",
                password="Passw0rd8",
                student_id=str(uuid.uuid4().int)[:10],
            )
        )
        await session.commit()
        return user.id


async def _seed_tagged_question(
    session: AsyncSession,
    author_id: uuid.UUID,
    *,
    title: str,
    tags: tuple[str, ...],
    created_at: datetime,
    status: QuestionStatus = QuestionStatus.OPEN,
) -> Question:
    """直接构造带目录标签的问题（F03 需控制 created_at 与标签集）。"""
    catalog = SqlAlchemyTagCatalogRepository(session)
    persisted = [await catalog.get_or_create(Tag(value=t)) for t in tags]
    question = Question(
        id=uuid.uuid4(),
        title=Title(title),
        body=Body("F03 相关推荐：标签共现排序测试正文"),
        author_id=author_id,
        created_at=created_at,
        status=status,
        tags=persisted,
    )
    await SqlAlchemyQuestionRepository(session).add(question)
    return question


async def _upvote_question(
    session: AsyncSession, user_id: uuid.UUID, question_id: uuid.UUID
) -> None:
    await SqlAlchemyVoteRepository(session).add(
        Vote.cast(
            user_id=user_id,
            target_type=VoteTarget.QUESTION,
            target_id=question_id,
            direction=VoteDirection.UP,
        )
    )


async def test_question_persists_and_roundtrips() -> None:
    author_id = await _make_author()
    async with session_factory() as session:
        use_case = AskQuestionUseCase(
            SqlAlchemyQuestionRepository(session), SqlAlchemyTagCatalogRepository(session)
        )
        question = await use_case.execute(
            AskQuestionCommand(
                title="  仓储回读测试标题  ",
                body="仓储回读测试正文",
                author_id=author_id,
            )
        )
        await session.commit()

        repo = SqlAlchemyQuestionRepository(session)
        fetched = await repo.get_by_id(question.id)
        assert fetched is not None
        assert fetched.id == question.id
        assert fetched.title.value == "仓储回读测试标题"  # 落库即规范化后形态
        assert fetched.body.value == "仓储回读测试正文"
        assert fetched.author_id == author_id
        assert fetched.created_at.tzinfo is not None


async def test_get_by_id_missing_returns_none() -> None:
    async with session_factory() as session:
        repo = SqlAlchemyQuestionRepository(session)
        assert await repo.get_by_id(uuid.uuid4()) is None


async def test_list_paginated_orders_and_slices_exactly() -> None:
    """全表 (created_at, id) 严格降序（确定性全序）+ offset/limit 与全量读取一致。

    种子用过去时间戳（不霸占列表头部，毒化其他测试的"最新"断言）；
    断言对表中既有数据零假设（容忍 page_size 窗口外数据）。
    """
    author_id = await _make_author()
    base = datetime(2020, 1, 1, tzinfo=UTC)
    seeds = [
        Question(
            id=uuid.uuid4(),
            title=Title(f"排序切片 {i}"),
            body=Body("正文"),
            author_id=author_id,
            created_at=base + timedelta(seconds=i),
        )
        for i in range(5)
    ]
    async with session_factory() as session:
        repo = SqlAlchemyQuestionRepository(session)
        for seed in seeds:
            await repo.add(seed)
        await session.commit()

        full_items, total = await repo.list_paginated(page=1, page_size=1000)
        assert total >= 5
        keys = [(q.created_at, q.id) for q in full_items]
        assert keys == sorted(keys, reverse=True)  # 全表降序无歧义

        # 在窗口内的种子呈新→旧相对序（种子时间戳最旧，通常整段在窗口末尾）
        seed_ids = {s.id for s in seeds}
        present = [q.id for q in full_items if q.id in seed_ids]
        expected_order = [s.id for s in reversed(seeds)]
        assert present == [i for i in expected_order if i in set(present)]

        # offset/limit 切片必须与同一全序的窗口完全一致
        page2_items, _ = await repo.list_paginated(page=2, page_size=3)
        assert [q.id for q in page2_items] == [q.id for q in full_items[3:6]]
        page3_items, _ = await repo.list_paginated(page=3, page_size=3)
        assert [q.id for q in page3_items] == [q.id for q in full_items[6:9]]


async def test_list_paginated_filters_by_closed_time_range() -> None:
    """F01：时间闭区间——边界行命中、区间外不命中，COUNT 与当前页同口径。"""
    author_id = await _make_author()
    base = datetime(2001, 1, 1, tzinfo=UTC)
    seeds = [
        Question(
            id=uuid.uuid4(),
            title=Title(f"时间筛选 {offset}"),
            body=Body("正文"),
            author_id=author_id,
            created_at=base + timedelta(seconds=offset),
        )
        for offset in (-1, 0, 1, 2)
    ]
    async with session_factory() as session:
        repo = SqlAlchemyQuestionRepository(session)
        for seed in seeds:
            await repo.add(seed)
        await session.commit()

        items, total = await repo.list_paginated(
            page=1,
            page_size=100000,
            filters=QuestionFilter(
                created_from=base, created_to=base + timedelta(seconds=1)
            ),
        )
        # 闭区间 [base, base+1s]：边界两行必中，区间外两行必不中；
        # 不假设窗口内无历史种子（本用例跨轮会累积），只断言成员与同口径
        ids = {q.id for q in items}
        assert {seeds[1].id, seeds[2].id} <= ids
        assert seeds[0].id not in ids
        assert seeds[3].id not in ids
        assert total == len(items)


async def test_list_paginated_tiebreaker_deterministic() -> None:
    """同微秒并发发帖（Q-12 连发场景）created_at 相同：按 id DESC 确定性定序。"""
    author_id = await _make_author()
    same_at = datetime(2019, 6, 1, tzinfo=UTC)
    qa = Question(
        id=uuid.uuid4(), title=Title("同刻甲"), body=Body("正文"),
        author_id=author_id, created_at=same_at,
    )
    qb = Question(
        id=uuid.uuid4(), title=Title("同刻乙"), body=Body("正文"),
        author_id=author_id, created_at=same_at,
    )
    async with session_factory() as session:
        repo = SqlAlchemyQuestionRepository(session)
        await repo.add(qa)
        await repo.add(qb)
        await session.commit()

        # 仓储端口无 page_size 上限（上限在路由层 le=100）；本地开发库经多轮
        # 暴力测试累积超千行，种子为 2019 旧时间戳排在窗口尾部，需大窗口保证可查
        items, _total = await repo.list_paginated(page=1, page_size=100000)
        ids = [q.id for q in items]
        ia, ib = ids.index(qa.id), ids.index(qb.id)
        # 同 created_at：id 大者在前（确定性全序，跨页不重复/不漏项）
        assert (ia < ib) == (qa.id > qb.id)


async def test_list_paginated_q_matches_title_and_body_once() -> None:
    """F02：标题命中、正文命中、双命中只出一行；无关数据不命中；total 同口径。"""
    author_id = await _make_author()
    token = uuid.uuid4().hex[:10]
    unrelated = uuid.uuid4().hex[:10]
    base = datetime(2022, 3, 1, tzinfo=UTC)
    seeds = [
        Question(
            id=uuid.uuid4(),
            title=Title(f"{token} 标题命中"),
            body=Body("普通正文"),
            author_id=author_id,
            created_at=base + timedelta(seconds=1),
        ),
        Question(
            id=uuid.uuid4(),
            title=Title("普通标题"),
            body=Body(f"正文包含 {token}"),
            author_id=author_id,
            created_at=base + timedelta(seconds=2),
        ),
        Question(
            id=uuid.uuid4(),
            title=Title(f"{token} 双命中"),
            body=Body(f"正文也含 {token}"),
            author_id=author_id,
            created_at=base + timedelta(seconds=3),
        ),
        Question(
            id=uuid.uuid4(),
            title=Title(f"{unrelated} 无关"),
            body=Body("无关正文"),
            author_id=author_id,
            created_at=base + timedelta(seconds=4),
        ),
    ]
    async with session_factory() as session:
        repo = SqlAlchemyQuestionRepository(session)
        for seed in seeds:
            await repo.add(seed)
        await session.commit()

        items, total = await repo.list_paginated(
            page=1, page_size=100000, filters=QuestionFilter(q=token)
        )
        ids = [q.id for q in items]
        assert seeds[0].id in ids
        assert seeds[1].id in ids
        assert ids.count(seeds[2].id) == 1  # 标题+正文双命中仍单行（OR 非 JOIN）
        assert seeds[3].id not in ids
        assert total == len(items)


async def test_list_paginated_q_is_case_insensitive() -> None:
    """F02：ILIKE 大小写不敏感（关键词小写也能命中大写标题）。"""
    author_id = await _make_author()
    token = uuid.uuid4().hex[:10]
    seed = Question(
        id=uuid.uuid4(),
        title=Title(f"{token} SQLAlchemy 事务"),
        body=Body("正文"),
        author_id=author_id,
        created_at=datetime(2022, 4, 1, tzinfo=UTC),
    )
    async with session_factory() as session:
        repo = SqlAlchemyQuestionRepository(session)
        await repo.add(seed)
        await session.commit()

        items, _total = await repo.list_paginated(
            page=1, page_size=100000, filters=QuestionFilter(q=f"{token} sqlalchemy")
        )
        assert [q.id for q in items] == [seed.id]


async def test_list_paginated_q_treats_wildcards_literally() -> None:
    """F02：% / _ / \\ 按字面匹配，不放大为通配符。"""
    author_id = await _make_author()
    token = uuid.uuid4().hex[:10]
    base = datetime(2022, 5, 1, tzinfo=UTC)
    percent_hit = Question(
        id=uuid.uuid4(),
        title=Title(f"{token} 100% 命中"),
        body=Body("正文"),
        author_id=author_id,
        created_at=base + timedelta(seconds=1),
    )
    percent_miss = Question(
        id=uuid.uuid4(),
        title=Title(f"{token} 100x 不应命中"),
        body=Body("正文"),
        author_id=author_id,
        created_at=base + timedelta(seconds=2),
    )
    underscore_hit = Question(
        id=uuid.uuid4(),
        title=Title("普通标题"),
        body=Body(f"{token} a_b"),
        author_id=author_id,
        created_at=base + timedelta(seconds=3),
    )
    underscore_miss = Question(
        id=uuid.uuid4(),
        title=Title("普通标题"),
        body=Body(f"{token} axb"),
        author_id=author_id,
        created_at=base + timedelta(seconds=4),
    )
    backslash_hit = Question(
        id=uuid.uuid4(),
        title=Title(f"{token} path\\to"),
        body=Body("正文"),
        author_id=author_id,
        created_at=base + timedelta(seconds=5),
    )
    backslash_miss = Question(
        id=uuid.uuid4(),
        title=Title(f"{token} pathXto"),
        body=Body("正文"),
        author_id=author_id,
        created_at=base + timedelta(seconds=6),
    )
    seeds = [
        percent_hit,
        percent_miss,
        underscore_hit,
        underscore_miss,
        backslash_hit,
        backslash_miss,
    ]
    async with session_factory() as session:
        repo = SqlAlchemyQuestionRepository(session)
        for seed in seeds:
            await repo.add(seed)
        await session.commit()

        async def _hits(q: str) -> set[uuid.UUID]:
            items, _total = await repo.list_paginated(
                page=1, page_size=100000, filters=QuestionFilter(q=q)
            )
            return {item.id for item in items}

        assert await _hits(f"{token} 100%") == {percent_hit.id}
        assert await _hits(f"{token} a_b") == {underscore_hit.id}
        assert await _hits(f"{token} path\\to") == {backslash_hit.id}


async def test_list_paginated_q_combines_with_status_filter() -> None:
    """F02 与 F01 组合：q + status 条件同时生效，total 与当前页同口径。"""
    author_id = await _make_author()
    token = uuid.uuid4().hex[:10]
    base = datetime(2022, 6, 1, tzinfo=UTC)
    open_seed = Question(
        id=uuid.uuid4(),
        title=Title(f"{token} 组合开"),
        body=Body("正文"),
        author_id=author_id,
        created_at=base + timedelta(seconds=1),
        status=QuestionStatus.OPEN,
    )
    closed_seed = Question(
        id=uuid.uuid4(),
        title=Title(f"{token} 组合关"),
        body=Body("正文"),
        author_id=author_id,
        created_at=base + timedelta(seconds=2),
        status=QuestionStatus.CLOSED,
    )
    async with session_factory() as session:
        repo = SqlAlchemyQuestionRepository(session)
        await repo.add(open_seed)
        await repo.add(closed_seed)
        await session.commit()

        open_items, open_total = await repo.list_paginated(
            page=1,
            page_size=100000,
            filters=QuestionFilter(q=token, status=QuestionStatus.OPEN),
        )
        assert [q.id for q in open_items] == [open_seed.id]
        assert open_total == len(open_items)

        closed_items, closed_total = await repo.list_paginated(
            page=1,
            page_size=100000,
            filters=QuestionFilter(q=token, status=QuestionStatus.CLOSED),
        )
        assert [q.id for q in closed_items] == [closed_seed.id]
        assert closed_total == len(closed_items)


# ============================================================
# F03 相关问题推荐：标签共现排序 / tiebreak / 自身排除 / limit / 边界
# ============================================================


async def test_list_related_orders_by_overlap_desc() -> None:
    """重合数降序：3 标签重合 > 2 标签重合 > 1 标签重合。"""
    author_id = await _make_author()
    token = uuid.uuid4().hex[:8]
    tag_a = f"F03{token}React"
    tag_b = f"F03{token}TypeScript"
    tag_c = f"F03{token}PostgreSQL"
    base = datetime(2023, 1, 1, tzinfo=UTC)
    async with session_factory() as session:
        source = await _seed_tagged_question(
            session, author_id, title="种子问题", tags=(tag_a, tag_b, tag_c), created_at=base
        )
        full = await _seed_tagged_question(
            session,
            author_id,
            title="三标签重合",
            tags=(tag_a, tag_b, tag_c),
            created_at=base + timedelta(seconds=1),
        )
        half = await _seed_tagged_question(
            session,
            author_id,
            title="两标签重合",
            tags=(tag_a, tag_b),
            created_at=base + timedelta(seconds=2),
        )
        one = await _seed_tagged_question(
            session,
            author_id,
            title="一标签重合",
            tags=(tag_a,),
            created_at=base + timedelta(seconds=3),
        )
        await session.commit()

        related = await SqlAlchemyQuestionRepository(session).list_related(source.id, 10)
        assert [q.id for q in related] == [full.id, half.id, one.id]


async def test_list_related_same_overlap_orders_by_net_votes() -> None:
    """重合数相同按净票数降序：有赞者压过更新但无赞者。"""
    author_id = await _make_author()
    voter_id = await _make_author()
    token = uuid.uuid4().hex[:8]
    tag_a = f"F03{token}React"
    tag_b = f"F03{token}TypeScript"
    base = datetime(2023, 2, 1, tzinfo=UTC)
    async with session_factory() as session:
        source = await _seed_tagged_question(
            session, author_id, title="种子问题", tags=(tag_a, tag_b), created_at=base
        )
        voted = await _seed_tagged_question(
            session,
            author_id,
            title="同重合有赞",
            tags=(tag_a, tag_b),
            created_at=base + timedelta(seconds=1),
        )
        unvoted = await _seed_tagged_question(
            session,
            author_id,
            title="同重合无赞",
            tags=(tag_a, tag_b),
            created_at=base + timedelta(seconds=2),
        )
        await _upvote_question(session, voter_id, voted.id)
        await session.commit()

        related = await SqlAlchemyQuestionRepository(session).list_related(source.id, 10)
        assert [q.id for q in related] == [voted.id, unvoted.id]


async def test_list_related_tiebreak_by_created_at_then_id() -> None:
    """重合与净票均相同：created_at 降序；同刻按 id 降序（全序）。"""
    author_id = await _make_author()
    token = uuid.uuid4().hex[:8]
    tag = f"F03{token}Redis"
    base = datetime(2023, 3, 1, tzinfo=UTC)
    async with session_factory() as session:
        source = await _seed_tagged_question(
            session, author_id, title="种子问题", tags=(tag,), created_at=base
        )
        old = await _seed_tagged_question(
            session,
            author_id,
            title="较旧",
            tags=(tag,),
            created_at=base + timedelta(seconds=1),
        )
        same_at = base + timedelta(seconds=2)
        new_a = await _seed_tagged_question(
            session, author_id, title="同刻甲", tags=(tag,), created_at=same_at
        )
        new_b = await _seed_tagged_question(
            session, author_id, title="同刻乙", tags=(tag,), created_at=same_at
        )
        await session.commit()

        related = await SqlAlchemyQuestionRepository(session).list_related(source.id, 10)
        same_at_order = sorted([new_a, new_b], key=lambda q: q.id, reverse=True)
        assert [q.id for q in related] == [
            same_at_order[0].id,
            same_at_order[1].id,
            old.id,
        ]


async def test_list_related_excludes_self_and_applies_limit() -> None:
    """自身恒不出现；limit 截断按排序取前 N。"""
    author_id = await _make_author()
    token = uuid.uuid4().hex[:8]
    tag = f"F03{token}Docker"
    base = datetime(2023, 4, 1, tzinfo=UTC)
    async with session_factory() as session:
        source = await _seed_tagged_question(
            session, author_id, title="种子问题", tags=(tag,), created_at=base
        )
        older = await _seed_tagged_question(
            session,
            author_id,
            title="较旧相关",
            tags=(tag,),
            created_at=base + timedelta(seconds=1),
        )
        middle = await _seed_tagged_question(
            session,
            author_id,
            title="中间相关",
            tags=(tag,),
            created_at=base + timedelta(seconds=2),
        )
        newest = await _seed_tagged_question(
            session,
            author_id,
            title="最新相关",
            tags=(tag,),
            created_at=base + timedelta(seconds=3),
        )
        await session.commit()

        repo = SqlAlchemyQuestionRepository(session)
        limited = await repo.list_related(source.id, 2)
        assert [q.id for q in limited] == [newest.id, middle.id]
        assert source.id not in {q.id for q in limited}

        all_items = await repo.list_related(source.id, 10)
        assert [q.id for q in all_items] == [newest.id, middle.id, older.id]


async def test_list_related_no_tags_returns_empty() -> None:
    """无标签问题短路返回空列表（可被推荐的候选不作任何匹配）。"""
    author_id = await _make_author()
    token = uuid.uuid4().hex[:8]
    tag = f"F03{token}Kafka"
    base = datetime(2023, 5, 1, tzinfo=UTC)
    async with session_factory() as session:
        source = await _seed_tagged_question(
            session, author_id, title="无标签种子", tags=(), created_at=base
        )
        await _seed_tagged_question(
            session,
            author_id,
            title="有标签候选",
            tags=(tag,),
            created_at=base + timedelta(seconds=1),
        )
        await session.commit()

        related = await SqlAlchemyQuestionRepository(session).list_related(source.id, 10)
        assert related == []


async def test_list_related_includes_closed_question() -> None:
    """D3：关闭问题仍可被推荐（不过滤状态）。"""
    author_id = await _make_author()
    token = uuid.uuid4().hex[:8]
    tag = f"F03{token}Vue"
    base = datetime(2023, 6, 1, tzinfo=UTC)
    async with session_factory() as session:
        source = await _seed_tagged_question(
            session, author_id, title="种子问题", tags=(tag,), created_at=base
        )
        closed = await _seed_tagged_question(
            session,
            author_id,
            title="已关闭相关",
            tags=(tag,),
            created_at=base + timedelta(seconds=1),
            status=QuestionStatus.CLOSED,
        )
        await session.commit()

        related = await SqlAlchemyQuestionRepository(session).list_related(source.id, 10)
        assert [q.id for q in related] == [closed.id]
        assert related[0].status is QuestionStatus.CLOSED


async def test_list_related_missing_question_returns_empty() -> None:
    """不存在的问题在仓储层返回空列表（404 语义由用例层负责）。"""
    async with session_factory() as session:
        related = await SqlAlchemyQuestionRepository(session).list_related(
            uuid.uuid4(), 10
        )
        assert related == []
