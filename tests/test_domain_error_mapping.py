"""C2 映射单测：DomainValidationError → 422；裸 ValueError 不得被误注册（→500）。

使用独立 mini FastAPI，不往 create_app() 注入测试路由——真实 app 的完整处理器链
会掩盖"映射模块是否误注册裸 ValueError"这一命题本身。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.platform.http.error_mapping import register_validation_error_handler
from app.shared.errors import DomainValidationError


def _client() -> TestClient:
    application = FastAPI()
    register_validation_error_handler(application)

    @application.get("/domain")
    def _domain() -> None:
        raise DomainValidationError("输入不合法")

    @application.get("/plain")
    def _plain() -> None:
        raise ValueError("程序 bug")

    return TestClient(application, raise_server_exceptions=False)


def test_domain_validation_error_maps_to_422_string_detail() -> None:
    response = _client().get("/domain")
    assert response.status_code == 422
    assert response.json() == {"detail": "输入不合法"}


def test_plain_value_error_is_not_mapped_to_422() -> None:
    response = _client().get("/plain")
    assert response.status_code == 500
