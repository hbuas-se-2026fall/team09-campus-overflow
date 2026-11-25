"""Question 聚合与 Title/Body 值对象单元测试（纯 Python，进 CI）。"""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from app.contexts.qa.domain.errors import (
    AcceptedAnswerCannotDeleteError,
    AnswerAlreadyAcceptedError,
    QuestionAlreadyClosedError,
    QuestionClosedError,
)
from app.contexts.qa.domain.question import (
    Question,
    QuestionClosed,
    QuestionPublished,
    QuestionStatus,
)
from app.contexts.qa.domain.value_objects import Body, Title
from app.shared.sentinel import UNSET


class TestTitle:
    def test_valid_title_is_stripped_and_stored(self) -> None:
        title = Title("  如何理解数据库第三范式？  ")
        assert title.value == "如何理解数据库第三范式？"

    @pytest.mark.parametrize("raw", ["", "   ", "\t", "\n  \t"])
    def test_blank_title_rejected(self, raw: str) -> None:
        with pytest.raises(ValueError):
            Title(raw)

    def test_single_char_title_allowed(self) -> None:
        assert Title("问").value == "问"

    def test_100_chars_allowed(self) -> None:
        assert Title("a" * 100).value == "a" * 100

    def test_101_chars_rejected(self) -> None:
        with pytest.raises(ValueError):
            Title("a" * 101)

    def test_unicode_counts_as_code_points(self) -> None:
        # 中文按码点计数：100 个汉字合法，101 个拒绝
        assert Title("数" * 100).value == "数" * 100
        with pytest.raises(ValueError):
            Title("数" * 101)

    def test_nul_rejected(self) -> None:
        with pytest.raises(ValueError, match="控制字符"):
            Title("a\x00b")

    def test_lone_surrogate_rejected(self) -> None:
        with pytest.raises(ValueError, match="代理字符"):
            Title("x\ud800y")

    def test_multiline_whitespace_allowed(self) -> None:
        # \t \n \r 是多行文本合法空白，不拦截
        assert Title("a\tb\nc").value == "a\tb\nc"


class TestBody:
    def test_valid_body_is_stripped_and_stored(self) -> None:
        assert Body("  正文内容……  ").value == "正文内容……"

    @pytest.mark.parametrize("raw", ["", " ", "\n\t "])
    def test_blank_body_rejected(self, raw: str) -> None:
        with pytest.raises(ValueError):
            Body(raw)

    def test_5000_chars_allowed(self) -> None:
        assert Body("x" * 5000).value == "x" * 5000

    def test_5001_chars_rejected(self) -> None:
        with pytest.raises(ValueError):
            Body("x" * 5001)

    def test_nul_rejected(self) -> None:
        with pytest.raises(ValueError, match="控制字符"):
            Body("x\x00y")

    def test_lone_surrogate_rejected(self) -> None:
        with pytest.raises(ValueError, match="代理字符"):
            Body("正文\ud800")


class TestQuestionAsk:
    def test_ask_creates_aggregate_and_publishes_event(self) -> None:
        author_id = uuid4()
        question = Question.ask(
            title_value="  什么是第三范式？  ",
            body_value=" 教材里讲得不太懂。 ",
            author_id=author_id,
        )

        assert isinstance(question.id, UUID)
        assert question.title.value == "什么是第三范式？"
        assert question.body.value == "教材里讲得不太懂。"
        assert question.author_id == author_id
        assert question.created_at.tzinfo is not None  # 带时区的 UTC 时间

        assert len(question.events) == 1
        event = question.events[0]
        assert isinstance(event, QuestionPublished)
        assert event.question_id == question.id
        assert event.author_id == author_id

    def test_ask_generates_distinct_ids(self) -> None:
        author_id = uuid4()
        q1 = Question.ask(title_value="问题一", body_value="正文", author_id=author_id)
        q2 = Question.ask(title_value="问题二", body_value="正文", author_id=author_id)
        assert q1.id != q2.id

    def test_ask_with_blank_title_raises(self) -> None:
        with pytest.raises(ValueError):
            Question.ask(title_value="   ", body_value="正文", author_id=uuid4())


class TestQuestionClose:
    """关闭态（US-Q08 迭代 5）：状态翻转 + 事件 + 不变式（重复关闭 / 已采纳不可关闭）。"""

    def test_close_sets_status_and_publishes_event(self) -> None:
        author_id = uuid4()
        question = Question.ask(title_value="标题", body_value="正文", author_id=author_id)

        question.close()

        assert question.status is QuestionStatus.CLOSED
        assert len(question.events) == 2
        closed = question.events[1]
        assert isinstance(closed, QuestionClosed)
        assert closed.question_id == question.id
        assert closed.author_id == author_id
        assert closed.occurred_at.tzinfo is not None

    def test_close_twice_rejected_and_status_kept(self) -> None:
        question = Question.ask(title_value="标题", body_value="正文", author_id=uuid4())
        question.close()
        with pytest.raises(QuestionAlreadyClosedError):
            question.close()
        assert question.status is QuestionStatus.CLOSED

    def test_close_with_accepted_answer_rejected(self) -> None:
        question = Question.ask(title_value="标题", body_value="正文", author_id=uuid4())
        question.mark_accepted(uuid4())
        with pytest.raises(AnswerAlreadyAcceptedError):
            question.close()
        assert question.status is QuestionStatus.OPEN


class TestQuestionEdit:
    """编辑（US-Q08 迭代 5，裁定 D6 仅标题+正文）：规范化更新 + 已关闭拒绝 + 半改防护。"""

    def test_edit_updates_and_normalizes(self) -> None:
        question = Question.ask(title_value="旧标题", body_value="旧正文", author_id=uuid4())

        question.edit_title_body(title_value="  新标题  ", body_value="  新正文  ")

        assert question.title.value == "新标题"
        assert question.body.value == "新正文"

    def test_edit_closed_question_rejected(self) -> None:
        question = Question.ask(title_value="标题", body_value="正文", author_id=uuid4())
        question.close()
        with pytest.raises(QuestionClosedError):
            question.edit_title_body(title_value="新标题", body_value="新正文")
        assert question.title.value == "标题"  # 未半改（全冻结：关闭后不可编辑）

    def test_edit_invalid_body_keeps_old_values(self) -> None:
        question = Question.ask(title_value="标题", body_value="正文", author_id=uuid4())
        with pytest.raises(ValueError):
            question.edit_title_body(title_value="新标题", body_value="   ")
        assert question.title.value == "标题"  # 值对象先构后赋：失败无半改状态
        assert question.body.value == "正文"


class TestQuestionSoftDelete:
    """软删除（F13，D1–D3）：活跃/已关闭均可删、重复删幂等返回 False、已采纳拒绝（409）。"""

    def test_soft_delete_open_question_sets_deleted_at_and_is_idempotent(self) -> None:
        question = Question.ask(
            title_value="PostgreSQL MVCC 如何通过 xmin/xmax 判断元组可见性？",
            body_value=(
                "在 READ COMMITTED 隔离级别下，每条语句生成新快照时如何结合 clog 判断事务状态？"
            ),
            author_id=uuid4(),
        )
        assert question.is_deleted is False

        first = question.soft_delete()
        first_at = question.deleted_at

        assert first is True
        assert question.is_deleted is True
        assert first_at is not None and first_at.tzinfo is not None

        second = question.soft_delete()
        assert second is False
        assert question.deleted_at == first_at

    def test_soft_delete_closed_question_allowed(self) -> None:
        question = Question.ask(
            title_value="B+ 树索引分裂时右兄弟指针的作用是什么？",
            body_value="高并发范围扫描与页面分裂同时发生时如何避免漏读？",
            author_id=uuid4(),
        )
        question.close()

        assert question.soft_delete() is True
        assert question.is_deleted is True

    def test_soft_delete_with_accepted_answer_rejected(self) -> None:
        question = Question.ask(
            title_value="为什么第三范式要求非主属性对候选键不存在传递函数依赖？",
            body_value="请结合选课关系表说明插入异常与删除异常的消除。",
            author_id=uuid4(),
        )
        question.mark_accepted(uuid4())

        with pytest.raises(AcceptedAnswerCannotDeleteError, match="已有采纳答案"):
            question.soft_delete()

        assert question.is_deleted is False
        assert question.deleted_at is None


class TestQuestionCourseAssociation:
    """F17：Question.ask / edit_title_body 可选 course_id 与 UNSET/None 语义。"""

    def test_ask_and_edit_course_id_semantics(self) -> None:
        cid1, cid2 = uuid4(), uuid4()
        q = Question.ask(
            title_value="事务隔离级别与幻读防止",
            body_value="PostgreSQL SSI 如何检测 rw-antidependency 环？",
            author_id=uuid4(),
            course_id=cid1,
        )
        assert q.course_id == cid1

        # 传 UNSET 保留既有 course_id
        q.edit_title_body(
            title_value="事务隔离级别与幻读防止（修订）",
            body_value="PostgreSQL SSI 如何检测 rw-antidependency 环？",
            course_id=UNSET,
        )
        assert q.course_id == cid1

        # 校验失败不半改 course_id
        with pytest.raises(ValueError):
            q.edit_title_body(title_value="   ", body_value="有效正文", course_id=cid2)
        assert q.course_id == cid1

        # 传新 course_id 变更，传 None 解绑
        q.edit_title_body(
            title_value="事务隔离级别与幻读防止（改课）",
            body_value="PostgreSQL SSI 如何检测 rw-antidependency 环？",
            course_id=cid2,
        )
        assert q.course_id == cid2

        q.edit_title_body(
            title_value="事务隔离级别与幻读防止（解绑）",
            body_value="PostgreSQL SSI 如何检测 rw-antidependency 环？",
            course_id=None,
        )
        assert q.course_id is None
