"""声誉事件发布供给面（reputation 公开供给面，v3.1 D-B）。

qa interfaces 仅 import 本模块（EventPublisherDep / DTO 类型），不触 reputation
内部基础设施；reputation 不 import qa——载荷以已发布语言 DTO 传递。

投递时机（D-B 选型）：BackgroundTasks 在响应发送后执行，而 scope="function" 下
get_session 退出代码（commit）在响应发送前完成——故实际 .delay 执行时数据已落库
（发布时序探针 R-07 实证）。本门面只做"延迟"，Celery 适配器按需在组合根内加载。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import BackgroundTasks, Depends

from app.contexts.reputation.application.ports import (
    AcceptEventPayload,
    EventPublisher,
    VoteEventPayload,
)


class DeferredEventPublisher:
    """FastAPI 延迟发布门面：把实际投递挂到 BackgroundTasks（响应发送后执行）。"""

    def __init__(self, background_tasks: BackgroundTasks, inner: EventPublisher) -> None:
        self._background_tasks = background_tasks
        self._inner = inner

    def publish_vote(self, payload: VoteEventPayload) -> None:
        self._background_tasks.add_task(self._inner.publish_vote, payload)

    def publish_accept(self, payload: AcceptEventPayload) -> None:
        self._background_tasks.add_task(self._inner.publish_accept, payload)


def get_event_publisher(background_tasks: BackgroundTasks) -> EventPublisher:
    """组合根：函数体内加载 Celery 适配器，qa 的 import 图保持无 Celery。"""
    from app.contexts.reputation.infrastructure.event_publisher import (
        CeleryEventPublisher,
    )

    return DeferredEventPublisher(background_tasks, CeleryEventPublisher())


EventPublisherDep = Annotated[EventPublisher, Depends(get_event_publisher)]
