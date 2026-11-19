"""徽章接口集成测试（F06）：公开访问、连续活跃徽章、404、无活动空徽章。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest

from app.contexts.qa.infrastructure.models import QuestionModel
from app.main import create_app
from app.shared.engine import session_factory

pytestmark = pytest.mark.integration

BASE_URL = "http://test"


@pytest.fixture
async def client(redis_cleanup: None) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url=BASE_URL) as c:
        yield c


async def _register(client: httpx.AsyncClient) -> str:
    payload: dict[str, Any] = {
        "role": "student",
        "email": f"{uuid.uuid4()}@stu.edu.cn",
        "password": "Passw0rd8",
        "student_id": str(uuid.uuid4().int)[:10],
    }
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def _seed_question_days(user_id: str, days: list[str]) -> None:
    async with session_factory() as session:
        for day in days:
            session.add(
                QuestionModel(
                    id=uuid.uuid4(),
                    title=f"徽章活跃日 {day}",
                    body="F06 徽章接口集成：按日发帖形成连续活跃。",
                    author_id=uuid.UUID(user_id),
                    created_at=datetime.fromisoformat(day).replace(
                        hour=4, tzinfo=UTC
                    ),
                    status="open",
                )
            )
        await session.commit()


async def test_badges_public_with_streak(client: httpx.AsyncClient) -> None:
    user_id = await _register(client)
    await _seed_question_days(user_id, ["2024-01-01", "2024-01-02", "2024-01-03"])

    resp = await client.get(f"/api/v1/users/{user_id}/badges")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["user_id"] == user_id
    assert data["answer_count"] == 0
    assert data["acceptance_rate"] == 0.0
    assert data["longest_streak_days"] == 3
    codes = {b["code"] for b in data["badges"]}
    assert "streak_3" in codes
    assert "answers_5" not in codes


async def test_badges_no_activity_returns_empty(client: httpx.AsyncClient) -> None:
    user_id = await _register(client)
    resp = await client.get(f"/api/v1/users/{user_id}/badges")
    assert resp.status_code == 200, resp.text
    assert resp.json()["badges"] == []
    assert resp.json()["longest_streak_days"] == 0


async def test_badges_missing_user_returns_404(client: httpx.AsyncClient) -> None:
    resp = await client.get(f"/api/v1/users/{uuid.uuid4()}/badges")
    assert resp.status_code == 404, resp.text
    assert resp.json()["detail"] == "用户不存在"
