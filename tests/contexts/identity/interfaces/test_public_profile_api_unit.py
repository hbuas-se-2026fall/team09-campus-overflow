"""F11 公开主页与下游回填接口单元测试（依赖覆盖，不连库，进 CI）。"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx

from app.contexts.discovery.domain.notification import (
    Notification,
    NotificationTargetType,
    NotificationType,
)
from app.contexts.discovery.interfaces.api.deps import get_notification_repository
from app.contexts.identity.application.ports import PublicUserProfile, UserSummary
from app.contexts.identity.domain.user import User
from app.contexts.identity.domain.value_objects import Nickname
from app.contexts.identity.interfaces.api.deps import (
    get_current_user,
    get_public_user_profile_reader,
    get_user_summary_reader,
)
from app.contexts.qa.domain.question import Question, QuestionStatus
from app.contexts.qa.domain.repository import QuestionSort
from app.contexts.qa.interfaces.api.deps import get_question_repository
from app.contexts.reputation.domain.leaderboard import LeaderboardRow
from app.contexts.reputation.interfaces.api.deps import (
    get_leaderboard_cache,
    get_reputation_ledger_repository,
)
from app.main import create_app


class _FakeProfileReader:
    def __init__(self, profiles: dict[UUID, PublicUserProfile]) -> None:
        self._profiles = profiles

    async def get_public_profile(self, user_id: UUID) -> PublicUserProfile | None:
        return self._profiles.get(user_id)


class _FakeSummaryReader:
    def __init__(self, summaries: dict[UUID, UserSummary]) -> None:
        self._summaries = summaries
        self.calls: list[list[UUID]] = []

    async def get_summaries(self, user_ids: object) -> dict[UUID, UserSummary]:
        ids = list(user_ids)  # type: ignore[arg-type]
        self.calls.append(ids)
        return {uid: self._summaries[uid] for uid in ids if uid in self._summaries}


async def test_public_profile_endpoint_200_and_404_unit() -> None:
    uid = UUID("11111111-1111-1111-1111-111111111111")
    app = create_app()
    app.dependency_overrides[get_public_user_profile_reader] = lambda: _FakeProfileReader(
        {
            uid: PublicUserProfile(
                user_id=uid,
                role="teacher",
                display_name="李老师",
                nickname="李老师",
                college="软件学院",
                class_name=None,
            )
        }
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        ok = await client.get(f"/api/v1/users/{uid}/profile")
        assert ok.status_code == 200
        body = ok.json()
        assert body == {
            "user_id": str(uid),
            "role": "teacher",
            "display_name": "李老师",
            "nickname": "李老师",
            "college": "软件学院",
            "class_name": None,
        }

        missing = await client.get(f"/api/v1/users/{uuid4()}/profile")
        assert missing.status_code == 404
        assert missing.json() == {"detail": "用户不存在"}


async def test_downstream_backfill_and_missing_user_fallback_unit() -> None:
    known_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    missing_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    now = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)

    fake_summary_reader = _FakeSummaryReader(
        {
            known_id: UserSummary(
                user_id=known_id, display_name="小张", role="student"
            )
        }
    )
    current_user = User.register(
        role="student",
        email_value="cur@stu.edu.cn",
        password_hash_value="$2b$12$abcdefghijklmnopqrstuv",
        identity_value="2025010101",
    )
    current_user.update_profile(nickname=Nickname("当前用户"))

    class _FakeQuestionRepo:
        async def list_paginated(
            self,
            page: int,
            page_size: int,
            sort: QuestionSort = QuestionSort.LATEST,
            filters: object = None,
        ) -> tuple[list[Question], int]:
            q1 = Question.ask(title_value="t1", body_value="b1", author_id=known_id)
            q2 = Question.ask(title_value="t2", body_value="b2", author_id=missing_id)
            return [q1, q2], 2

    class _FakeLedgerRepo:
        async def list_top(
            self, start: datetime, end: datetime, limit: int
        ) -> list[LeaderboardRow]:
            return [
                LeaderboardRow(user_id=known_id, score=20, rank=1),
                LeaderboardRow(user_id=missing_id, score=10, rank=2),
            ]

    class _FakeCache:
        async def get(self, *args: object) -> None:
            return None

        async def set(self, *args: object) -> None:
            return None

    class _FakeNotificationRepo:
        async def list_paginated(
            self,
            recipient_id: UUID,
            page: int,
            page_size: int,
            unread_only: bool,
        ) -> tuple[list[Notification], int]:
            item = Notification(
                id=uuid4(),
                recipient_id=recipient_id,
                type=NotificationType.ANSWER_POSTED,
                actor_id=missing_id,
                target_type=NotificationTargetType.ANSWER,
                target_id=uuid4(),
                source_event_id=uuid4(),
                question_id=uuid4(),
                is_read=False,
                created_at=now,
            )
            return [item], 1

    app = create_app()
    app.dependency_overrides[get_user_summary_reader] = lambda: fake_summary_reader
    app.dependency_overrides[get_current_user] = lambda: current_user
    app.dependency_overrides[get_question_repository] = lambda: _FakeQuestionRepo()
    app.dependency_overrides[get_reputation_ledger_repository] = (
        lambda: _FakeLedgerRepo()
    )
    app.dependency_overrides[get_leaderboard_cache] = lambda: _FakeCache()
    app.dependency_overrides[get_notification_repository] = (
        lambda: _FakeNotificationRepo()
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        q_resp = await client.get("/api/v1/questions")
        assert q_resp.status_code == 200
        q_items = q_resp.json()["items"]
        assert [i["author_name"] for i in q_items] == ["小张", "未知用户"]
        assert q_items[0]["status"] == QuestionStatus.OPEN.value

        lb_resp = await client.get("/api/v1/leaderboard")
        assert lb_resp.status_code == 200
        assert [e["display_name"] for e in lb_resp.json()["entries"]] == [
            "小张",
            "未知用户",
        ]

        n_resp = await client.get("/api/v1/notifications")
        assert n_resp.status_code == 200
        assert [n["actor_name"] for n in n_resp.json()["items"]] == ["未知用户"]
