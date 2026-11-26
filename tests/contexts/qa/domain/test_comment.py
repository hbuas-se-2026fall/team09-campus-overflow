"""Comment 领域实体与二级回复不变式单测（F14，无外部依赖，进 CI）。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.contexts.qa.domain.comment import Comment, CommentTarget
from app.contexts.qa.domain.value_objects import Body
from app.shared.errors import DomainValidationError


def test_comment_write_root_and_second_level_reply() -> None:
    qid = uuid4()
    alice = uuid4()
    bob = uuid4()

    root = Comment.write(
        target_type=CommentTarget.QUESTION,
        target_id=qid,
        author_id=alice,
        body_value="  关于 B+ 树叶子节点双向链表的范围查询复杂度  ",
    )
    assert root.parent_id is None
    assert root.body.value == "关于 B+ 树叶子节点双向链表的范围查询复杂度"
    assert root.events[0].parent_id is None

    reply = Comment.write(
        target_type=CommentTarget.QUESTION,
        target_id=qid,
        author_id=bob,
        body_value="范围扫描先定位左边界 O(log N)，再沿叶链表线性遍历 O(K)。",
        parent=root,
    )
    assert reply.parent_id == root.id
    assert reply.events[0].parent_id == root.id


def test_comment_write_allows_replying_to_own_root_comment() -> None:
    aid = uuid4()
    alice = uuid4()
    root = Comment.write(
        target_type=CommentTarget.ANSWER,
        target_id=aid,
        author_id=alice,
        body_value="一级答评",
    )
    self_reply = Comment.write(
        target_type=CommentTarget.ANSWER,
        target_id=aid,
        author_id=alice,
        body_value="补充一条自己的二级回复",
        parent=root,
    )
    assert self_reply.parent_id == root.id


def test_comment_validate_parent_rejects_third_level_reply() -> None:
    qid = uuid4()
    root = Comment.write(
        target_type=CommentTarget.QUESTION,
        target_id=qid,
        author_id=uuid4(),
        body_value="一级评论",
    )
    second = Comment.write(
        target_type=CommentTarget.QUESTION,
        target_id=qid,
        author_id=uuid4(),
        body_value="二级回复",
        parent=root,
    )
    with pytest.raises(DomainValidationError, match="评论仅支持二级回复，不可回复二级评论"):
        Comment.write(
            target_type=CommentTarget.QUESTION,
            target_id=qid,
            author_id=uuid4(),
            body_value="试图发三级回复",
            parent=second,
        )


def test_comment_validate_parent_rejects_cross_host_target_id_or_type() -> None:
    qid1, qid2 = uuid4(), uuid4()
    root_on_q1 = Comment.write(
        target_type=CommentTarget.QUESTION,
        target_id=qid1,
        author_id=uuid4(),
        body_value="问题 1 的一级评论",
    )

    with pytest.raises(DomainValidationError, match="父评论不属于当前对象"):
        Comment.write(
            target_type=CommentTarget.QUESTION,
            target_id=qid2,
            author_id=uuid4(),
            body_value="跨问题回复",
            parent=root_on_q1,
        )

    with pytest.raises(DomainValidationError, match="父评论不属于当前对象"):
        Comment.write(
            target_type=CommentTarget.ANSWER,
            target_id=qid1,
            author_id=uuid4(),
            body_value="同 UUID 但跨 target_type 回复",
            parent=root_on_q1,
        )


def test_comment_rejects_self_parent_invariant() -> None:
    cid = uuid4()
    with pytest.raises(DomainValidationError, match="评论不能回复自身"):
        Comment(
            id=cid,
            target_type=CommentTarget.QUESTION,
            target_id=uuid4(),
            author_id=uuid4(),
            body=Body("非法自引用"),
            created_at=datetime.now(UTC),
            parent_id=cid,
        )
