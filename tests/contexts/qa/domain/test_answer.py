"""Answer 聚合领域单元测试（F12：edit_body 与不变式）。"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.contexts.qa.domain.answer import Answer
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
