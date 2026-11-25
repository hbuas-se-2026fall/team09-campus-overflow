"""F17 问题关联课程与课程贡献榜 PG 仓储集成测试。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, func, select

from app.contexts.course.domain.course import Course
from app.contexts.course.infrastructure.course_repository import (
    SqlAlchemyCourseRepository,
)
from app.contexts.course.infrastructure.models import CourseModel
from app.contexts.identity.domain.user import User
from app.contexts.identity.infrastructure.models import UserModel
from app.contexts.identity.infrastructure.repository import SqlAlchemyUserRepository
from app.contexts.qa.domain.answer import Answer
from app.contexts.qa.domain.question import Question
from app.contexts.qa.domain.repository import QuestionFilter
from app.contexts.qa.domain.vote import Vote, VoteDirection, VoteTarget
from app.contexts.qa.infrastructure.answer_repository import SqlAlchemyAnswerRepository
from app.contexts.qa.infrastructure.course_leaderboard_repository import (
    SqlAlchemyCourseLeaderboardRepository,
)
from app.contexts.qa.infrastructure.models import QuestionModel
from app.contexts.qa.infrastructure.question_repository import (
    SqlAlchemyQuestionRepository,
)
from app.contexts.qa.infrastructure.vote_repository import SqlAlchemyVoteRepository
from app.contexts.reputation.infrastructure.models import ReputationLedgerModel
from app.shared.engine import session_factory

pytestmark = pytest.mark.integration


def _make_user(role: str, prefix: str) -> User:
    ident = (
        str(uuid.uuid4().int)[:10]
        if role == "student"
        else f"T{uuid.uuid4().int % 90_000_000 + 10_000_000}"
    )
    return User.register(
        role=role,  # type: ignore[arg-type]
        email_value=f"{prefix}-{uuid.uuid4().hex[:8]}@campus.edu.cn",
        password_hash_value="$2b$12$abcdefghijklmnopqrstuv",
        identity_value=ident,
    )


async def test_question_course_filter_and_leaderboard_aggregation() -> None:
    suffix = uuid.uuid4().hex[:6].upper()
    teacher = _make_user("teacher", "f17-t")
    u1 = _make_user("student", "f17-u1")
    u2 = _make_user("student", "f17-u2")
    u3 = _make_user("student", "f17-u3")
    voter1 = _make_user("student", "f17-v1")
    voter2 = _make_user("student", "f17-v2")
    voter3 = _make_user("student", "f17-v3")
    all_users = [teacher, u1, u2, u3, voter1, voter2, voter3]

    course = Course.create(
        code=f"CS-DB-{suffix}",
        name="数据库系统原理",
        semester=f"2026-Fall-{suffix}",
        teacher_id=teacher.id,
    )
    other_course = Course.create(
        code=f"CS-OS-{suffix}",
        name="操作系统",
        semester=f"2026-Fall-{suffix}",
        teacher_id=teacher.id,
    )

    q_active_1 = Question.ask(
        title_value="B+ 树聚簇索引与二级索引回表代价分析",
        body_value="为什么 InnoDB 二级索引叶子节点存放主键值？",
        author_id=teacher.id,
        course_id=course.id,
    )
    q_active_2 = Question.ask(
        title_value="PostgreSQL MVCC 真空清理（VACUUM）原理",
        body_value="如何理解 frozen xid 与事务 ID 回卷？",
        author_id=teacher.id,
        course_id=course.id,
    )
    q_deleted = Question.ask(
        title_value="已软删课程问题不应计入榜单",
        body_value="软删除后所有下属回答须被课程榜单剔除。",
        author_id=teacher.id,
        course_id=course.id,
    )
    q_other = Question.ask(
        title_value="操作系统 Clock 页面置换算法",
        body_value="来自另一门课程的问题。",
        author_id=teacher.id,
        course_id=other_course.id,
    )

    # u1: 1 accepted + 2 answers (one with 3 upvotes -> net_votes=3, NOT 3*answers)
    a_u1_1 = Answer.post(
        question_id=q_active_1.id,
        body_value="主键值保持行迁移零级联更新。",
        author_id=u1.id,
    )
    a_u1_2 = Answer.post(
        question_id=q_active_2.id,
        body_value="autovacuum 推进 datfrozenxid。",
        author_id=u1.id,
    )

    # u2: same accepted_count=1 and net_votes=3 -> tied rank=1, 1 answer (< u1's 2)
    a_u2_1 = Answer.post(
        question_id=q_active_2.id,
        body_value="可见性映射 VM 加速全表扫描。",
        author_id=u2.id,
    )

    # u3: 0 accepted, 1 net vote -> rank=3
    a_u3_1 = Answer.post(
        question_id=q_active_1.id,
        body_value="覆盖索引可避免回表。",
        author_id=u3.id,
    )
    # 软删回答与软删问题下的回答均不可计入榜单
    a_u3_deleted = Answer.post(
        question_id=q_active_1.id, body_value="已删回答", author_id=u3.id
    )
    a_under_deleted_q = Answer.post(
        question_id=q_deleted.id, body_value="已删问题下回答", author_id=u3.id
    )

    course_ids = [course.id, other_course.id]
    question_ids = [q_active_1.id, q_active_2.id, q_deleted.id, q_other.id]
    user_ids = [u.id for u in all_users]

    try:
        async with session_factory() as session:
            user_repo = SqlAlchemyUserRepository(session)
            for user in all_users:
                await user_repo.add(user)
            c_repo = SqlAlchemyCourseRepository(session)
            await c_repo.add(course)
            await c_repo.add(other_course)
            q_repo = SqlAlchemyQuestionRepository(session)
            for q in (q_active_1, q_active_2, q_deleted, q_other):
                await q_repo.add(q)
            a_repo = SqlAlchemyAnswerRepository(session)
            for a in (a_u1_1, a_u1_2, a_u2_1, a_u3_1, a_u3_deleted, a_under_deleted_q):
                await a_repo.add(a)
            # 先落库答案后再双写采纳状态与软删除
            a_u1_1.accept()
            q_active_1.mark_accepted(a_u1_1.id)
            a_u2_1.accept()
            q_active_2.mark_accepted(a_u2_1.id)
            await q_repo.update(q_active_1)
            await q_repo.update(q_active_2)
            await a_repo.update(a_u1_1)
            await a_repo.update(a_u2_1)
            await a_repo.soft_delete(a_u3_deleted.id, datetime.now(UTC) + timedelta(seconds=1))
            await q_repo.soft_delete(q_deleted.id, datetime.now(UTC) + timedelta(seconds=2))

            v_repo = SqlAlchemyVoteRepository(session)
            # a_u1_1 得 3 赞 (net=3)
            for voter in (voter1, voter2, voter3):
                await v_repo.add(
                    Vote.cast(
                        user_id=voter.id,
                        target_type=VoteTarget.ANSWER,
                        target_id=a_u1_1.id,
                        direction=VoteDirection.UP,
                    )
                )
            # a_u2_1 得 3 赞 (net=3)
            for voter in (voter1, voter2, voter3):
                await v_repo.add(
                    Vote.cast(
                        user_id=voter.id,
                        target_type=VoteTarget.ANSWER,
                        target_id=a_u2_1.id,
                        direction=VoteDirection.UP,
                    )
                )
            # a_u3_1 得 1 赞
            await v_repo.add(
                Vote.cast(
                    user_id=voter1.id,
                    target_type=VoteTarget.ANSWER,
                    target_id=a_u3_1.id,
                    direction=VoteDirection.UP,
                )
            )
            await session.commit()

        async with session_factory() as session:
            q_repo = SqlAlchemyQuestionRepository(session)
            items, total = await q_repo.list_paginated(
                page=1,
                page_size=10,
                filters=QuestionFilter(course_id=course.id),
            )
            assert total == 2
            assert {item.id for item in items} == {q_active_1.id, q_active_2.id}

            # 验证多票不膨胀、软删排除、RANK 同分同名次（1, 1, 3）及 reputation_ledgers 零写入
            lb_repo = SqlAlchemyCourseLeaderboardRepository(session)
            entries = await lb_repo.list_top_contributors(course.id, limit=20)
            assert len(entries) == 3

            # u1 与 u2 同为 accepted=1, net_votes=3 -> 同 rank=1，
            # u1 (answer_count=2) 排在 u2 (answer_count=1) 之前
            assert entries[0].user_id == u1.id
            assert entries[0].accepted_count == 1
            assert entries[0].net_votes == 3
            assert entries[0].answer_count == 2
            assert entries[0].rank == 1

            assert entries[1].user_id == u2.id
            assert entries[1].accepted_count == 1
            assert entries[1].net_votes == 3
            assert entries[1].answer_count == 1
            assert entries[1].rank == 1

            assert entries[2].user_id == u3.id
            assert entries[2].accepted_count == 0
            assert entries[2].net_votes == 1
            assert entries[2].answer_count == 1
            assert entries[2].rank == 3

            assert await lb_repo.list_top_contributors(other_course.id, limit=20) == []

            rep_rows = int(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(ReputationLedgerModel)
                        .where(ReputationLedgerModel.user_id.in_(user_ids))
                    )
                ).scalar_one()
            )
            assert rep_rows == 0
    finally:
        async with session_factory() as session:
            await session.execute(
                delete(QuestionModel).where(QuestionModel.id.in_(question_ids))
            )
            await session.execute(
                delete(CourseModel).where(CourseModel.id.in_(course_ids))
            )
            await session.execute(
                delete(UserModel).where(UserModel.id.in_(user_ids))
            )
            await session.commit()
