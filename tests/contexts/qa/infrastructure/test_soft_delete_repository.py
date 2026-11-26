"""软删除仓储与活跃统计集成测试（F13，真 PostgreSQL）。

测试数据遵循真实知识约束，题材取自 PostgreSQL 官方文档：
- https://www.postgresql.org/docs/current/btree-implementation.html
- https://www.postgresql.org/docs/current/routine-vacuuming.html
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.contexts.identity.application.commands import RegisterCommand
from app.contexts.identity.application.register_use_case import RegisterUseCase
from app.contexts.identity.infrastructure.password_hasher import BcryptPasswordHasher
from app.contexts.identity.infrastructure.repository import SqlAlchemyUserRepository
from app.contexts.qa.domain.answer import Answer
from app.contexts.qa.domain.comment import Comment, CommentTarget
from app.contexts.qa.domain.errors import (
    AcceptedAnswerCannotDeleteError,
    AnswerNotFoundError,
    QuestionNotFoundError,
)
from app.contexts.qa.domain.question import Question
from app.contexts.qa.domain.repository import QuestionFilter, QuestionSort
from app.contexts.qa.domain.tag import Tag
from app.contexts.qa.domain.value_objects import Body, Title
from app.contexts.qa.domain.vote import Vote, VoteDirection, VoteTarget
from app.contexts.qa.infrastructure.answer_repository import SqlAlchemyAnswerRepository
from app.contexts.qa.infrastructure.comment_repository import SqlAlchemyCommentRepository
from app.contexts.qa.infrastructure.models import AnswerModel, QuestionModel
from app.contexts.qa.infrastructure.question_repository import SqlAlchemyQuestionRepository
from app.contexts.qa.infrastructure.tag_repository import SqlAlchemyTagCatalogRepository
from app.contexts.qa.infrastructure.user_activity_repository import (
    SqlAlchemyUserActivityRepository,
)
from app.contexts.qa.infrastructure.vote_repository import SqlAlchemyVoteRepository
from app.shared.engine import session_factory

pytestmark = pytest.mark.integration


async def _create_student() -> uuid.UUID:
    async with session_factory() as session:
        user = await RegisterUseCase(
            SqlAlchemyUserRepository(session), BcryptPasswordHasher()
        ).execute(
            RegisterCommand(
                role="student",
                email=f"pg-mvcc-{uuid.uuid4().hex[:10]}@stu.edu.cn",
                password="Passw0rd8",
                student_id=str(uuid.uuid4().int)[:10],
            )
        )
        await session.commit()
        return user.id


async def test_question_soft_delete_guards_and_same_session_refresh() -> None:
    asker_id = await _create_student()
    answerer_id = await _create_student()
    now = datetime.now(UTC)

    async with session_factory() as session:
        q_repo = SqlAlchemyQuestionRepository(session)
        a_repo = SqlAlchemyAnswerRepository(session)

        q_open = Question.ask(
            title_value="PostgreSQL B-Tree 去重（Deduplication）如何压缩低基数索引？",
            body_value="当大量 MVCC 元组具有相同键值时，posting list 如何组织 TID 列表？",
            author_id=asker_id,
        )
        q_accepted = Question.ask(
            title_value="PostgreSQL HOT 更新需要满足哪些页面与索引前置条件？",
            body_value="如果被更新列包含在任意 B-Tree 索引中，为什么无法触发 Heap-Only Tuple？",
            author_id=asker_id,
        )
        await q_repo.add(q_open)
        await q_repo.add(q_accepted)

        ans = Answer.post(
            question_id=q_accepted.id,
            author_id=answerer_id,
            body_value="HOT 要求更新不修改任何索引列，且新元组能放入原堆页并由行指针链串联。",
        )
        await a_repo.add(ans)
        ans.accept()
        q_accepted.mark_accepted(ans.id)
        await a_repo.update(ans)
        await q_repo.update(q_accepted)
        await session.commit()

    # 同一会话内预加载 QuestionModel，验证 soft_delete 后 get_by_id 的 populate_existing 刷新
    async with session_factory() as session:
        preloaded = (
            await session.execute(
                select(QuestionModel).where(QuestionModel.id == q_open.id)
            )
        ).scalar_one()
        assert preloaded.deleted_at is None

        q_repo = SqlAlchemyQuestionRepository(session)
        assert await q_repo.soft_delete(q_open.id, now) is True
        # 重复软删除返回 False（幂等）
        assert await q_repo.soft_delete(q_open.id, now + timedelta(seconds=5)) is False

        # 默认 get_by_id 过滤已删行
        assert await q_repo.get_by_id(q_open.id) is None
        # include_deleted=True 可读且刷新同会话 identity map
        reloaded = await q_repo.get_by_id(q_open.id, include_deleted=True)
        assert reloaded is not None and reloaded.is_deleted is True
        assert preloaded.deleted_at is not None

        # 已采纳问题在库级被条件 WHERE 拦截 → 409
        with pytest.raises(AcceptedAnswerCannotDeleteError):
            await q_repo.soft_delete(q_accepted.id, now)

        # 不存在问题 → 404
        with pytest.raises(QuestionNotFoundError):
            await q_repo.soft_delete(uuid.uuid4(), now)

        # D6：对已软删除问题调用 update（无论编辑还是关闭意图）必须转译 404，不能误报 409
        q_open.edit_title_body(
            title_value="试图更新已软删除的问题标题",
            body_value="试图更新已软删除的问题正文",
        )
        with pytest.raises(QuestionNotFoundError):
            await q_repo.update(q_open)

        q_open.close()
        with pytest.raises(QuestionNotFoundError):
            await q_repo.update(q_open)

        await session.commit()


async def test_question_list_paginated_and_related_exclude_soft_deleted() -> None:
    asker_id = await _create_student()
    base = datetime(2025, 5, 1, 10, 0, tzinfo=UTC)
    keyword = f"MVCCVacuum{uuid.uuid4().hex[:6]}"
    tag_name = f"pgbtree{uuid.uuid4().hex[:4]}"

    async with session_factory() as session:
        tag_repo = SqlAlchemyTagCatalogRepository(session)
        q_repo = SqlAlchemyQuestionRepository(session)
        tag = await tag_repo.get_or_create(Tag(value=tag_name))

        q_alive = Question(
            id=uuid.uuid4(),
            title=Title(f"{keyword} 可见性映射如何跳过全部可见页"),
            body=Body("Visibility Map 用两位标记 all-visible 与 all-frozen 状态。"),
            author_id=asker_id,
            created_at=base,
            tags=[tag],
        )
        q_deleted = Question(
            id=uuid.uuid4(),
            title=Title(f"{keyword} B-Tree 死索引项回收时机"),
            body=Body("maintenance_work_mem 决定单轮 VACUUM 可收集的死 TID 数量。"),
            author_id=asker_id,
            created_at=base + timedelta(minutes=1),
            tags=[tag],
        )
        await q_repo.add(q_alive)
        await q_repo.add(q_deleted)
        await session.commit()

    async with session_factory() as session:
        q_repo = SqlAlchemyQuestionRepository(session)
        before_all, before_total = await q_repo.list_paginated(page=1, page_size=100000)
        assert {q_alive.id, q_deleted.id} <= {q.id for q in before_all}

        await q_repo.soft_delete(q_deleted.id, datetime.now(UTC))
        await session.commit()

        # 1. 无筛选列表（filters=None）与 total 同口径排除已删问题（D8）
        after_all, after_total = await q_repo.list_paginated(
            page=1, page_size=100000, filters=None
        )
        after_ids = {q.id for q in after_all}
        assert q_alive.id in after_ids
        assert q_deleted.id not in after_ids
        assert after_total == before_total - 1

        # 2. 关键词 + 标签 + votes 排序同样排除已删问题
        filtered, filtered_total = await q_repo.list_paginated(
            page=1,
            page_size=20,
            sort=QuestionSort.VOTES,
            filters=QuestionFilter(q=keyword, tags=(tag_name,)),
        )
        assert [q.id for q in filtered] == [q_alive.id]
        assert filtered_total == 1

        # 3. 相关推荐候选排除已删问题；已删种子自身返回空列表
        related = await q_repo.list_related(q_alive.id, limit=5)
        assert q_deleted.id not in [q.id for q in related]
        assert await q_repo.list_related(q_deleted.id, limit=5) == []


async def test_answer_repository_soft_delete_and_parent_deleted_isolation() -> None:
    asker_id = await _create_student()
    author_id = await _create_student()
    now = datetime.now(UTC)

    async with session_factory() as session:
        q_repo = SqlAlchemyQuestionRepository(session)
        a_repo = SqlAlchemyAnswerRepository(session)

        q1 = Question.ask(
            title_value="PostgreSQL Bottom-Up 索引删除如何缓解版本抖动造成的页分裂？",
            body_value="高频更新非索引列却跨页时，B-Tree 叶子页如何在分裂前自清理？",
            author_id=asker_id,
        )
        q2 = Question.ask(
            title_value="PostgreSQL autovacuum_vacuum_scale_factor 默认阈值如何计算触发行？",
            body_value="触发阈值 = threshold + scale_factor * reltuples 的适用场景与调优。",
            author_id=asker_id,
        )
        await q_repo.add(q1)
        await q_repo.add(q2)

        a1 = Answer.post(
            question_id=q1.id,
            author_id=author_id,
            body_value="在插入新索引项即将触发页面分裂时，先检查并移除指向死元组的索引条目。",
        )
        a_accepted = Answer.post(
            question_id=q1.id,
            author_id=author_id,
            body_value="已被采纳的权威解答：通过访问堆页验证快照下不可见的旧版本并就地回收。",
        )
        a_under_q2 = Answer.post(
            question_id=q2.id,
            author_id=author_id,
            body_value="当死元组数超过 vacuum threshold + scale_factor * 表行数时触发自动清理。",
        )
        await a_repo.add(a1)
        await a_repo.add(a_accepted)
        await a_repo.add(a_under_q2)

        a_accepted.accept()
        q1.mark_accepted(a_accepted.id)
        await a_repo.update(a_accepted)
        await q_repo.update(q1)
        await session.commit()

    async with session_factory() as session:
        preloaded = (
            await session.execute(select(AnswerModel).where(AnswerModel.id == a1.id))
        ).scalar_one()
        assert preloaded.deleted_at is None

        a_repo = SqlAlchemyAnswerRepository(session)
        q_repo = SqlAlchemyQuestionRepository(session)

        # 软删除未采纳回答成功，重复删返回 False
        assert await a_repo.soft_delete(a1.id, now) is True
        assert await a_repo.soft_delete(a1.id, now + timedelta(seconds=1)) is False
        assert await a_repo.get_by_id(a1.id) is None
        inc = await a_repo.get_by_id(a1.id, include_deleted=True)
        assert inc is not None and inc.is_deleted is True
        assert preloaded.deleted_at is not None

        # list_by_question 仅返回未删回答
        assert [a.id for a in await a_repo.list_by_question(q1.id)] == [a_accepted.id]

        # 已采纳回答不可软删 → 409
        with pytest.raises(AcceptedAnswerCannotDeleteError):
            await a_repo.soft_delete(a_accepted.id, now)

        # D6：对已软删除回答执行 update / update_body 必须抛 AnswerNotFoundError（404）
        with pytest.raises(AnswerNotFoundError):
            await a_repo.update(a1)
        a1.edit_body(body_value="试图编辑已删回答")
        with pytest.raises(AnswerNotFoundError):
            await a_repo.update_body(a1)

        # D4/D6：软删除父问题 q2（不级联写 a_under_q2.deleted_at）后，
        # get_by_id / list_by_question / update / update_body / soft_delete 均因父问题已删拦截
        assert await q_repo.soft_delete(q2.id, now) is True
        assert await a_repo.get_by_id(a_under_q2.id) is None
        assert await a_repo.list_by_question(q2.id) == []
        with pytest.raises(QuestionNotFoundError):
            await a_repo.update(a_under_q2)
        with pytest.raises(QuestionNotFoundError):
            await a_repo.update_body(a_under_q2)
        with pytest.raises(QuestionNotFoundError):
            await a_repo.soft_delete(a_under_q2.id, now)

        await session.commit()


async def test_user_activity_repository_excludes_all_six_soft_deleted_sources() -> None:
    """F13 D5 + 补充项 1：answer_stats 与 active_dates 全量剔除 6 路已删/父已删记录。"""
    user_id = await _create_student()
    other_id = await _create_student()

    # 构造 7 个不同上海自然日（04:00 UTC = 12:00 Asia/Shanghai）：
    # D1..D6 随后分别通过不同路径进入软删除态，仅 D7 保持完全活跃
    d1 = datetime(2024, 3, 1, 4, tzinfo=UTC)  # 用户自己发的 question（随后该题被软删）
    d2 = datetime(2024, 3, 2, 4, tzinfo=UTC)  # 用户的 answer（随后该回答本身被软删）
    d3 = datetime(2024, 3, 3, 4, tzinfo=UTC)  # 用户的 answer（随后其父问题被软删）
    d4 = datetime(2024, 3, 4, 4, tzinfo=UTC)  # 用户的题评 + 题票（随后宿主问题被软删）
    d5 = datetime(2024, 3, 5, 4, tzinfo=UTC)  # 用户的答评 + 答票（随后宿主回答被软删）
    d6 = datetime(2024, 3, 6, 4, tzinfo=UTC)  # 用户的答评 + 答票（随后宿主回答的父问题被软删）
    d7 = datetime(2024, 3, 7, 4, tzinfo=UTC)  # 唯一保留活跃的回答

    async with session_factory() as session:
        q_repo = SqlAlchemyQuestionRepository(session)
        a_repo = SqlAlchemyAnswerRepository(session)
        c_repo = SqlAlchemyCommentRepository(session)
        v_repo = SqlAlchemyVoteRepository(session)

        # Q1：用户自己在 D1 发的问题（将直接软删）
        q1 = Question(
            id=uuid.uuid4(),
            title=Title("PostgreSQL 事务 ID 回卷（Wraparound）与冻结阈值原理"),
            body=Body("vacuum_freeze_min_age 与 autovacuum_freeze_max_age 如何协同防止 XID 回卷？"),
            author_id=user_id,
            created_at=d1,
        )
        # Q_alive：他人一直保持活跃的问题（承载 D2 被删回答、D5 被删回答上的答评/答票、D7 存活回答）
        q_alive = Question(
            id=uuid.uuid4(),
            title=Title("PostgreSQL B-Tree 叶子节点右向指针与高并发分裂机制"),
            body=Body("Lehman-Yao 算法如何在不持有整棵树锁的前提下完成并发查找与分裂？"),
            author_id=other_id,
            created_at=d1,
        )
        # Q_parent_del：他人发的问题，承载 D3 未删回答、D4 题评/题票、D6 答评/答票（随后整题软删）
        q_parent_del = Question(
            id=uuid.uuid4(),
            title=Title("PostgreSQL Visibility Map 的 all-frozen 位对全表 VACUUM 的加速作用"),
            body=Body("已标记 all-frozen 的堆页为何在激进冻结扫描中也可直接跳过？"),
            author_id=other_id,
            created_at=d1,
        )
        for q in (q1, q_alive, q_parent_del):
            await q_repo.add(q)

        # D2：用户在 q_alive 下的回答（自身将被软删）
        a_self_del = Answer(
            id=uuid.uuid4(),
            question_id=q_alive.id,
            author_id=user_id,
            body=Body("B-link 节点在分裂时先建立右兄弟指针，查找线程比较 high key 即可右移。"),
            created_at=d2,
        )
        # D3：用户在 q_parent_del 下的回答（自身不删，但父问题 q_parent_del 将被软删）
        a_parent_del = Answer(
            id=uuid.uuid4(),
            question_id=q_parent_del.id,
            author_id=user_id,
            body=Body(
                "all-frozen 位表明页面内所有元组均已冻结为 FrozenTransactionId，无需再次扫描。"
            ),
            created_at=d3,
        )
        # 他人在 q_alive 下的回答（供用户在 D5 发表答评+答票，随后该回答自身被软删）
        a_host_self_del = Answer(
            id=uuid.uuid4(),
            question_id=q_alive.id,
            author_id=other_id,
            body=Body("索引页内通过行指针数组按序折半查找，分裂点选在使两侧空间均衡的位置。"),
            created_at=d1,
        )
        # 他人在 q_parent_del 下的回答（供用户在 D6 发表答评+答票，随后父问题 q_parent_del 被软删）
        a_host_parent_del = Answer(
            id=uuid.uuid4(),
            question_id=q_parent_del.id,
            author_id=other_id,
            body=Body("Visibility Map 每个堆页占 2 bit，保存在主分叉旁的 _vm 分叉文件中。"),
            created_at=d1,
        )
        # D7：用户在 q_alive 下一直存活且被采纳的回答
        a_alive = Answer(
            id=uuid.uuid4(),
            question_id=q_alive.id,
            author_id=user_id,
            body=Body("Lehman-Yao 协议每次自底向上加锁至多同时锁住同一层两个相邻节点，避免死锁。"),
            created_at=d7,
            is_accepted=True,
        )
        for a in (
            a_self_del,
            a_parent_del,
            a_host_self_del,
            a_host_parent_del,
            a_alive,
        ):
            await a_repo.add(a)
        q_alive.mark_accepted(a_alive.id)
        await q_repo.update(q_alive)

        # D4：用户对 q_parent_del 的题评与题票
        await c_repo.add(
            Comment(
                id=uuid.uuid4(),
                target_type=CommentTarget.QUESTION,
                target_id=q_parent_del.id,
                author_id=user_id,
                body=Body("补充：PostgreSQL 9.6 起引入第二个 bit 记录 all-frozen。"),
                created_at=d4,
            )
        )
        await v_repo.add(
            Vote(
                id=uuid.uuid4(),
                user_id=user_id,
                target_type=VoteTarget.QUESTION,
                target_id=q_parent_del.id,
                direction=VoteDirection.UP,
                created_at=d4,
            )
        )

        # D5：用户对 a_host_self_del 的答评与答票
        await c_repo.add(
            Comment(
                id=uuid.uuid4(),
                target_type=CommentTarget.ANSWER,
                target_id=a_host_self_del.id,
                author_id=user_id,
                body=Body("PostgreSQL 14 还加入了后缀截断以减短内节点分裂键长度。"),
                created_at=d5,
            )
        )
        await v_repo.add(
            Vote(
                id=uuid.uuid4(),
                user_id=user_id,
                target_type=VoteTarget.ANSWER,
                target_id=a_host_self_del.id,
                direction=VoteDirection.UP,
                created_at=d5,
            )
        )

        # D6：用户对 a_host_parent_del 的答评与答票
        await c_repo.add(
            Comment(
                id=uuid.uuid4(),
                target_type=CommentTarget.ANSWER,
                target_id=a_host_parent_del.id,
                author_id=user_id,
                body=Body("一旦堆页发生 UPDATE/DELETE，对应 VM 位的两个 bit 都会被同步清除。"),
                created_at=d6,
            )
        )
        await v_repo.add(
            Vote(
                id=uuid.uuid4(),
                user_id=user_id,
                target_type=VoteTarget.ANSWER,
                target_id=a_host_parent_del.id,
                direction=VoteDirection.UP,
                created_at=d6,
            )
        )
        await session.commit()

        activity = SqlAlchemyUserActivityRepository(session)
        # 软删除前：用户有 3 条回答（1 采纳），7 个连续活跃自然日
        assert await activity.answer_stats(user_id) == (3, 1)
        assert [d.isoformat() for d in await activity.active_dates(user_id)] == [
            "2024-03-01",
            "2024-03-02",
            "2024-03-03",
            "2024-03-04",
            "2024-03-05",
            "2024-03-06",
            "2024-03-07",
        ]

        # 执行软删除：q1（D1）、a_self_del（D2）、a_host_self_del（D5）、q_parent_del（D3/D4/D6）
        del_time = datetime.now(UTC)
        assert await q_repo.soft_delete(q1.id, del_time) is True
        assert await a_repo.soft_delete(a_self_del.id, del_time) is True
        assert await a_repo.soft_delete(a_host_self_del.id, del_time) is True
        assert await q_repo.soft_delete(q_parent_del.id, del_time) is True
        await session.commit()

        # 软删除后：D1..D6 全部被剔除，仅剩 D7（1 条被采纳回答，1 个活跃日）
        assert await activity.answer_stats(user_id) == (1, 1)
        assert [d.isoformat() for d in await activity.active_dates(user_id)] == [
            "2024-03-07"
        ]
