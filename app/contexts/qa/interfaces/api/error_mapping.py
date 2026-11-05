"""qa 领域错误 → HTTP 状态码的唯一映射（interfaces 层）。

域层与用例层只抛业务语义异常，不感知 HTTP；本模块是 qa 上下文唯一的翻译处。
新增领域错误时只在此表登记，路由无需再逐个 try/except。

注意：领域异常处理器必须【返回】响应对象。Starlette 的 ExceptionMiddleware
在 handler 内部不再二次分发异常——若 handler 里 raise HTTPException，会越过
ExceptionMiddleware 直落 ServerErrorMiddleware，最终变成 500。
"""

from __future__ import annotations

from fastapi import FastAPI, status

from app.contexts.qa.domain import errors as qa_errors
from app.platform.http.error_mapping import make_domain_error_handler

# 领域错误 → HTTP 状态码，唯一出处（与既有路由语义逐条对齐）
QA_ERROR_STATUS: dict[type[Exception], int] = {
    qa_errors.QuestionNotFoundError: status.HTTP_404_NOT_FOUND,
    qa_errors.AnswerNotFoundError: status.HTTP_404_NOT_FOUND,
    qa_errors.NotQuestionAuthorError: status.HTTP_403_FORBIDDEN,
    qa_errors.AlreadyVotedError: status.HTTP_409_CONFLICT,
    qa_errors.AnswerAlreadyAcceptedError: status.HTTP_409_CONFLICT,
    qa_errors.QuestionAlreadyClosedError: status.HTTP_409_CONFLICT,
    qa_errors.QuestionClosedError: status.HTTP_409_CONFLICT,
}


def register_qa_error_handlers(application: FastAPI) -> None:
    """按类注册；Starlette 按 MRO 查找，具体类优先于基类。"""
    for exc_type, status_code in QA_ERROR_STATUS.items():
        application.add_exception_handler(exc_type, make_domain_error_handler(status_code))
