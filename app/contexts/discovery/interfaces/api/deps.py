"""discovery 组合根（F04）：仓储与写入适配器唯一装配处。

qa interfaces 只 import 本文件的工厂（interfaces→interfaces 护栏允许），
qa 应用层只依赖自身 NotificationWriter 端口。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.contexts.discovery.domain.repository import NotificationRepository
from app.contexts.discovery.infrastructure.notification_repository import (
    SqlAlchemyNotificationRepository,
)
from app.contexts.discovery.infrastructure.notification_writer import (
    SqlAlchemyNotificationWriter,
)
from app.platform.http.deps import SessionDep


def get_notification_repository(session: SessionDep) -> NotificationRepository:
    return SqlAlchemyNotificationRepository(session)


def get_notification_writer(session: SessionDep) -> SqlAlchemyNotificationWriter:
    return SqlAlchemyNotificationWriter(session)


NotificationRepo = Annotated[
    NotificationRepository, Depends(get_notification_repository)
]
NotificationWriterDep = Annotated[
    SqlAlchemyNotificationWriter, Depends(get_notification_writer)
]
