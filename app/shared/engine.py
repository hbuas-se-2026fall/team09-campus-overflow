from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.settings import get_settings


def _connect_args() -> dict[str, Any]:
    settings = get_settings()
    # 服务端语句/锁等待超时（第八路观察点 2）：防外部行锁令请求无上限挂起
    return {
        "timeout": settings.db_connect_timeout,
        "server_settings": {
            "statement_timeout": str(settings.db_statement_timeout_ms),
            "lock_timeout": str(settings.db_lock_timeout_ms),
        },
    }


def build_engine(*, force_null_pool: bool = False) -> AsyncEngine:
    """构建 AsyncEngine；连接参数单源（HTTP 与 Celery worker 共用）。

    force_null_pool=True 供 worker 使用：任务内 asyncio.run() 每次新建事件循环，
    池化连接会在跨 loop 复用时失效，必须强制 NullPool。
    """
    settings = get_settings()
    if not force_null_pool and settings.db_pool_size > 0:
        # 池化模式（仅哨兵 >0 时启用；0 绝不能传入池——SQLAlchemy 的 pool_size=0 是无上限池）。
        # pre_ping/recycle 防 WSL2/Docker NAT 静默丢弃空闲连接；上限 = pool_size+max_overflow。
        return create_async_engine(
            settings.database_url,
            poolclass=pool.AsyncAdaptedQueuePool,
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_max_overflow,
            pool_timeout=settings.db_pool_timeout,
            pool_pre_ping=True,
            pool_recycle=1800,
            connect_args=_connect_args(),
        )
    # NullPool：不复用连接。代价是每次请求新建连接（本机 ~1ms），
    # 换取对 pytest 多事件循环 / uvicorn --reload 的免疫（默认路径，测试/CI 零影响）。
    return create_async_engine(
        settings.database_url,
        poolclass=pool.NullPool,
        connect_args=_connect_args(),
    )


engine = build_engine()
session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """请求级会话依赖（事务边界在退出代码中提交/回滚）。

    注意：**所有使用点**须声明 ``Depends(get_session, scope="function")``——
    FastAPI ≥0.106 默认在响应【发送后】执行 yield 依赖的退出代码，commit 会落后于
    响应，造成"201 后亚秒级立即级联请求读不到数据"的可见性窗口（register→login 401、
    题目→立即建答 404）；scope="function" 使退出代码在响应【数据生成后、发送前】执行，
    commit 先于响应返回（详见台账 8.3 遗留项与 ADR-003）。
    """
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
