"""F11 读模型角色收敛与展示名辅助纯逻辑单元测试（不连库，进 CI）。"""

from __future__ import annotations

import logging
from uuid import UUID

import pytest

from app.contexts.identity.application.ports import UserSummary
from app.contexts.identity.infrastructure.user_summary_reader import _resolve_user_role
from app.contexts.qa.interfaces.api._common import display_name_for


def test_resolve_user_role_empty_falls_back_to_student() -> None:
    uid = UUID("11111111-1111-1111-1111-111111111111")
    assert _resolve_user_role(uid, []) == "student"
    assert _resolve_user_role(uid, [None]) == "student"


def test_resolve_user_role_prefers_teacher_over_student_and_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    uid = UUID("22222222-2222-2222-2222-222222222222")
    with caplog.at_level(logging.WARNING):
        picked = _resolve_user_role(uid, ["student", "teacher"])
    assert picked == "teacher"
    assert "多角色脏数据" in caplog.text
    assert str(uid) in caplog.text


def test_resolve_user_role_unknown_roles_sorted_after_known_roles() -> None:
    uid = UUID("33333333-3333-3333-3333-333333333333")
    assert _resolve_user_role(uid, ["ta", "admin", "student"]) == "student"
    assert _resolve_user_role(uid, ["ta", "admin"]) == "admin"


def test_display_name_for_falls_back_for_missing_user() -> None:
    uid = UUID("44444444-4444-4444-4444-444444444444")
    missing = UUID("55555555-5555-5555-5555-555555555555")
    summaries = {uid: UserSummary(user_id=uid, display_name="张同学", role="student")}
    assert display_name_for(summaries, uid) == "张同学"
    assert display_name_for(summaries, missing) == "未知用户"
