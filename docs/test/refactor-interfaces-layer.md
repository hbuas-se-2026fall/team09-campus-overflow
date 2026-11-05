# interfaces 层重构回归台账（2026-11-05）

## 1. 范围

组合根收拢（qa / identity）、领域错误 → HTTP 状态码集中映射、identity 令牌 TTL 与登录锁定阈值构造注入、Celery worker 引擎改用共享 `build_engine`。领域层/应用层/数据库/OpenAPI 均未改。

## 2. 方法与结果

| 检查项 | 命令 / 方法 | 结果 |
|:---|:---|:---|
| 静态检查 | `python -m ruff check app tests scripts` | **0 问题**（全目录 `ruff check .` 会扫到本地未跟踪 `._pydebs/`，非项目代码） |
| 类型检查 | `python -m mypy app`（strict） | **89 文件 0 错误** |
| 契约防漂移 | `python scripts/export_openapi.py --check` | **一致**（异常处理器不进 OpenAPI，无 spec 变化） |
| 应用装配冒烟 | `python -c "from app.main import create_app; create_app()"` | 通过（10 routes，Protocol 依赖注解被 FastAPI 接受） |
| 不依赖外部服务测试 | `pytest -q` 指定 health/body_limit/text_validation/validation_handlers/jwt_security + qa/identity/reputation 的 domain 目录 | **109 passed** |
| 错误映射行为 | 临时 FastAPI 应用逐个抛出 7 类领域错误（qa 404/403/409、identity 409/401/423/422），`TestClient(raise_server_exceptions=False)` | **7/7 状态码与 `{"detail": ...}` 形制正确** |
| 全量 pytest | `pytest -q` | **阻断**：本机 PostgreSQL/Redis 未运行（pg5432=False / redis6379=False），111 failed 全部为 `503 服务暂时不可用` 或 `ConnectionRefusedError`，无逻辑失败 |

## 3. 待补

容器（Postgres/Redis）拉起后再跑一次全量 `pytest -q`，确认 API 层错误码回归（404/403/409/422/401/423）与并发场景无回归；结果补记本文件。
