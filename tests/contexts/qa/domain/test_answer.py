"""Answer 聚合领域单元测试（F12：edit_body 与不变式）。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.contexts.qa.domain.answer import Answer
from app.contexts.qa.domain.errors import AcceptedAnswerCannotDeleteError
from app.shared.errors import DomainValidationError


def test_answer_edit_body_strips_and_preserves_status() -> None:
    answer = Answer.post(question_id=uuid4(), author_id=uuid4(), body_value="初始回答")
    answer.accept()

    answer.edit_body(body_value="  更新后的回答正文  ")

    assert answer.body.value == "更新后的回答正文"
    assert answer.is_accepted is True


@pytest.mark.parametrize("bad_body", ["", "   ", "a" * 5001, "x\x00y", "bad\ud800"])
def test_answer_edit_body_rejects_invalid_body(bad_body: str) -> None:
    answer = Answer.post(question_id=uuid4(), author_id=uuid4(), body_value="原始正文")

    with pytest.raises(DomainValidationError):
        answer.edit_body(body_value=bad_body)

    assert answer.body.value == "原始正文"


def test_answer_soft_delete_unaccepted_and_idempotent() -> None:
    answer = Answer.post(
        question_id=uuid4(),
        author_id=uuid4(),
        body_value="PostgreSQL 通过元组头部的 t_xmin 与 t_xmax 配合事务快照判断行版本可见性。",
    )
    assert answer.is_deleted is False

    assert answer.soft_delete() is True
    first_at = answer.deleted_at
    assert answer.is_deleted is True
    assert first_at is not None

    assert answer.soft_delete() is False
    assert answer.deleted_at == first_at


def test_answer_soft_delete_accepted_rejected() -> None:
    answer = Answer.post(
        question_id=uuid4(),
        author_id=uuid4(),
        body_value="B-link 树在内部节点与叶子节点引入 high key 和右向指针以支持无锁并发下行。",
    )
    answer.accept()

    with pytest.raises(AcceptedAnswerCannotDeleteError, match="已采纳的回答不可删除"):
        answer.soft_delete()

    assert answer.is_deleted is False
    assert answer.deleted_at is None


def test_answer_verify_and_unverify_are_idempotent_and_preserved_across_edits() -> None:
    answer = Answer.post(
        question_id=uuid4(),
        author_id=uuid4(),
        body_value="PostgreSQL 中 MVCC 通过事务快照可见性规则避免读写互相阻塞。",
    )
    assert answer.is_teacher_verified is False
    assert answer.verified_by is None
    assert answer.verified_at is None

    teacher_a = uuid4()
    teacher_b = uuid4()
    t1 = datetime(2026, 11, 25, 10, 0, tzinfo=UTC)
    t2 = datetime(2026, 11, 25, 11, 0, tzinfo=UTC)

    assert answer.verify(teacher_a, at=t1) is True
    assert answer.is_teacher_verified is True
    assert answer.verified_by == teacher_a
    assert answer.verified_at == t1

    # 幂等：重复认证保持原认证人与时间不变
    assert answer.verify(teacher_b, at=t2) is False
    assert answer.verified_by == teacher_a
    assert answer.verified_at == t1

    # edit_body 与 accept 保留既有认证状态
    answer.edit_body(body_value="PostgreSQL MVCC 结合 HOT 更新减少了索引膨胀。")
    answer.accept()
    assert answer.is_teacher_verified is True
    assert answer.verified_by == teacher_a
    assert answer.verified_at == t1

    # 取消认证与重复取消幂等
    assert answer.unverify() is True
    assert answer.is_teacher_verified is False
    assert answer.verified_by is None
    assert answer.verified_at is None
    assert answer.unverify() is False
