"""CommentRepository 二级回复集成测试（F14）：真 PostgreSQL。

覆盖：get_by_id 回读（存在/不存在）、二级回复持久化与 list_by_target 平铺有序返回、
数据库级约束实证（ck_comments_no_self_parent 拒自引用、fk_comments_parent_id 拒删父评）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError

from app.contexts.identity.application.commands import RegisterCommand
from app.contexts.identity.application.register_use_case import RegisterUseCase
from app.contexts.identity.infrastructure.password_hasher import BcryptPasswordHasher
from app.contexts.identity.infrastructure.repository import SqlAlchemyUserRepository
from app.contexts.qa.domain.comment import Comment, CommentTarget
from app.contexts.qa.domain.question import Question
from app.contexts.qa.domain.value_objects import Body, Title
from app.contexts.qa.infrastructure.comment_repository import SqlAlchemyCommentRepository
from app.contexts.qa.infrastructure.models import CommentModel
from app.contexts.qa.infrastructure.question_repository import SqlAlchemyQuestionRepository
from app.shared.engine import session_factory

pytestmark = pytest.mark.integration

_BASE = datetime(2017, 2, 1, tzinfo=UTC)


async def _make_author() -> uuid.UUID:
    async with session_factory() as session:
        use_case = RegisterUseCase(
            SqlAlchemyUserRepository(session), BcryptPasswordHasher()
        )
        user = await use_case.execute(
            RegisterCommand(
                role="student",
                email=f"f14-repo-{uuid.uuid4().hex[:10]}@stu.edu.cn",
                password="Passw0rd8",
                student_id=str(uuid.uuid4().int)[:10],
            )
        )
        await session.commit()
        return user.id


async def _make_question(author_id: uuid.UUID) -> Question:
    q = Question(
        id=uuid.uuid4(),
        title=Title(f"操作系统多级反馈队列调度与饥饿问题 {uuid.uuid4().hex[:6]}"),
        body=Body("在多级反馈队列（MLFQ）中，如何通过定期优先级提升避免低优先级进程饥饿？"),
        author_id=author_id,
        created_at=_BASE,
    )
    async with session_factory() as session:
        await SqlAlchemyQuestionRepository(session).add(q)
        await session.commit()
    return q


async def test_comment_get_by_id_and_flat_reply_ordering() -> None:
    author = await _make_author()
    q = await _make_question(author)

    root = Comment(
        id=uuid.uuid4(),
        target_type=CommentTarget.QUESTION,
        target_id=q.id,
        author_id=author,
        body=Body("一级评论：MLFQ 规则 5 会在固定周期 S 将所有作业重置到最高优先级队列。"),
        created_at=_BASE + timedelta(seconds=1),
    )
    reply_late = Comment(
        id=uuid.uuid4(),
        target_type=CommentTarget.QUESTION,
        target_id=q.id,
        author_id=author,
        body=Body("二级回复 B：若周期 S 过长，长耗时作业仍会饥饿。"),
        created_at=_BASE + timedelta(seconds=3),
        parent_id=root.id,
    )
    reply_early = Comment(
        id=uuid.uuid4(),
        target_type=CommentTarget.QUESTION,
        target_id=q.id,
        author_id=author,
        body=Body("二级回复 A：若周期 S 过短，交互式任务响应时间会恶化。"),
        created_at=_BASE + timedelta(seconds=2),
        parent_id=root.id,
    )

    async with session_factory() as session:
        repo = SqlAlchemyCommentRepository(session)
        await repo.add(root)
        await repo.add(reply_late)
        await repo.add(reply_early)
        await session.commit()

    async with session_factory() as session:
        repo = SqlAlchemyCommentRepository(session)
        assert await repo.get_by_id(uuid.uuid4()) is None

        loaded_root = await repo.get_by_id(root.id)
        loaded_reply = await repo.get_by_id(reply_early.id)
        assert loaded_root is not None and loaded_root.parent_id is None
        assert loaded_reply is not None and loaded_reply.parent_id == root.id

        listed = await repo.list_by_target(CommentTarget.QUESTION, q.id)
        assert [c.id for c in listed] == [root.id, reply_early.id, reply_late.id]
        assert [c.parent_id for c in listed] == [None, root.id, root.id]


async def test_db_constraints_reject_self_parent_and_restrict_parent_delete() -> None:
    """库级兜底：ck_comments_no_self_parent 禁止自引用；fk_comments_parent_id RESTRICT 禁删父评。"""
    author = await _make_author()
    q = await _make_question(author)

    # 1. CHECK 约束：绕过领域层直接写 parent_id == id 必须触发 IntegrityError
    self_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(
            CommentModel(
                id=self_id,
                body="尝试写入自引用行",
                target_type=CommentTarget.QUESTION.value,
                target_id=q.id,
                author_id=author,
                parent_id=self_id,
                created_at=_BASE,
            )
        )
        with pytest.raises(IntegrityError):
            await session.flush()
        await session.rollback()

    # 2. RESTRICT 外键：存在二级回复时禁止物理删除父评论
    root = Comment.write(
        target_type=CommentTarget.QUESTION,
        target_id=q.id,
        author_id=author,
        body_value="一级父评论（受 RESTRICT 保护）",
    )
    reply = Comment.write(
        target_type=CommentTarget.QUESTION,
        target_id=q.id,
        author_id=author,
        body_value="引用父评论的二级回复",
        parent=root,
    )
    async with session_factory() as session:
        repo = SqlAlchemyCommentRepository(session)
        await repo.add(root)
        await repo.add(reply)
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(delete(CommentModel).where(CommentModel.id == root.id))
            await session.flush()
        await session.rollback()
