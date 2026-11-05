"""HTTP 层共享装配面（平台组件）：仅放框架相关、跨上下文复用的依赖声明。

与 ``app/shared`` 的边界：shared 是框架无关的稳定内核（engine/redis/text_validation），
本包允许 import FastAPI/Starlette。**不要把本包内容反向放进 shared/engine.py**——
Celery worker 也 import build_engine，会连带拉起 FastAPI。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.shared.engine import get_session

SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
