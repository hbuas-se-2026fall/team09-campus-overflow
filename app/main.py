import logging

import asyncpg  # type: ignore[import-untyped]  # asyncpg 无 py.typed，mypy strict 下豁免
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import DBAPIError, SQLAlchemyError
from sqlalchemy.exc import TimeoutError as SATimeoutError

from app.config.settings import DEFAULT_EMAIL_VERIFY_HMAC_SECRET, get_settings
from app.contexts.discovery.interfaces.api.routes import (
    router as discovery_router,
)
from app.contexts.identity.interfaces.api.error_mapping import (
    register_identity_error_handlers,
)
from app.contexts.identity.interfaces.api.routes import router as auth_router
from app.contexts.qa.interfaces.api.error_mapping import register_qa_error_handlers
from app.contexts.qa.interfaces.api.routes import answers_router as qa_answers_router
from app.contexts.qa.interfaces.api.routes import badges_router as qa_badges_router
from app.contexts.qa.interfaces.api.routes import bounty_router as qa_bounty_router
from app.contexts.qa.interfaces.api.routes import points_router as qa_points_router
from app.contexts.qa.interfaces.api.routes import router as qa_router
from app.contexts.qa.interfaces.api.routes import tags_router as qa_tags_router
from app.contexts.reputation.interfaces.api.routes import (
    leaderboard_router,
    reputation_router,
)
from app.platform.http.body_limit import BodyLimitMiddleware
from app.platform.http.error_mapping import register_validation_error_handler
from app.platform.http.exception_handlers import (
    db_unavailable_handler,
    dbapi_error_handler,
    request_validation_exception_handler,
    sqlalchemy_error_handler,
)

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.email_verify_hmac_secret == DEFAULT_EMAIL_VERIFY_HMAC_SECRET:
        if settings.app_env == "prod":
            raise RuntimeError("生产环境禁止使用默认 email_verify_hmac_secret")
        logger.warning("当前使用默认 email_verify_hmac_secret，仅限开发/测试环境")
    application = FastAPI(title=settings.app_name, debug=settings.debug)
    application.add_middleware(BodyLimitMiddleware)
    # 422 不回显 input（治 surrogate/递归炸弹 500）；数据库错误统一 400 兜底
    application.add_exception_handler(RequestValidationError, request_validation_exception_handler)
    # 输入校验错误（值对象/目录/令牌载荷）统一 422：字符串形 detail，与旧路由兜底一致
    register_validation_error_handler(application)
    application.add_exception_handler(SQLAlchemyError, sqlalchemy_error_handler)
    # 容量工程（F-2 修复）：连接类错误 → 503——DBAPIError 分流 + asyncpg 裸异常 + 池排队超时
    application.add_exception_handler(DBAPIError, dbapi_error_handler)
    application.add_exception_handler(SATimeoutError, db_unavailable_handler)
    application.add_exception_handler(asyncpg.exceptions.PostgresError, db_unavailable_handler)
    application.add_exception_handler(asyncpg.exceptions.InterfaceError, db_unavailable_handler)
    # PG 不可达（进程死/端口关）时 asyncpg 抛 ConnectionRefusedError（OSError 族，非 asyncpg
    # 异常树）——第五路 D 路实证的 503 分层缺口：注册 ConnectionError 全族兜底
    application.add_exception_handler(ConnectionError, db_unavailable_handler)
    # PG"黑洞"（不拒连）时 asyncpg 建连超时抛内置 TimeoutError（asyncio.TimeoutError 同类，
    # connect_args timeout 到期）——第六路实测的 503 分层缺口；池排队超时仍由更具体的
    # sqlalchemy.exc.TimeoutError 命中（MRO 先精确）
    application.add_exception_handler(TimeoutError, db_unavailable_handler)
    # 领域错误 → HTTP 状态码：每上下文各自拥有映射表，此处只做组装
    register_identity_error_handlers(application)
    register_qa_error_handlers(application)
    application.include_router(auth_router)
    application.include_router(qa_router)
    application.include_router(qa_answers_router)
    application.include_router(qa_tags_router)
    application.include_router(qa_badges_router)
    application.include_router(qa_bounty_router)
    application.include_router(qa_points_router)
    application.include_router(reputation_router)
    application.include_router(leaderboard_router)
    application.include_router(discovery_router)

    @application.get("/health", tags=["ops"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return application


app = create_app()
