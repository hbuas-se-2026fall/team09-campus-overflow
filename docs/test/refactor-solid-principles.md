# SOLID/包结构重构回归台账（2026-11-05）

## 1. 范围

只做已批准的 P0-2 事件发布 DIP、P1-1 关闭态内聚、P0-1 组合根收拢、P1-2/P1-3 轻量去重、P2-1 架构护栏五项。领域规则、HTTP 状态码、消息文案、OpenAPI 契约、数据库结构与迁移均未改。

暂缓项（未动）：`DomainValidationError` 全局映射与删除 5 处 `ValueError→422`、`_make_handler` 抽取、`qa/infrastructure/repository.py` 与 `qa/interfaces/api/routes.py` 拆文件、refresh/logout 用例化。

## 2. 改动清单

| 项 | 文件 | 内容 |
|:---|:---|:---|
| ① | `app/contexts/reputation/domain/repository.py`（新增） | `ReputationLedgerRepository` 端口从 application 迁回 domain，与 qa/identity 一致 |
| ① | `app/contexts/reputation/application/ports.py`（重写） | `EventPublisher` 协议 + `VoteEventPayload`/`AcceptEventPayload` 已发布语言 DTO |
| ① | `app/contexts/reputation/infrastructure/event_publisher.py`（新增） | `CeleryEventPublisher`：DTO→JSON 安全 dict（UUID/datetime 字符串化）单源 + `.delay`；异常仅记日志（at-most-once，ADR-004） |
| ① | `app/contexts/reputation/interfaces/publisher.py`（重写） | `DeferredEventPublisher`（BackgroundTasks 延迟）+ `get_event_publisher`（函数体内加载 Celery 适配器）+ `EventPublisherDep` |
| ① | `app/contexts/qa/interfaces/api/routes.py` | 删除 `_event_payload`（asdict/UUID/datetime 序列化下沉）；新增 `_vote_payload`/`_accept_payload` 字段映射；三个端点改 `publisher: EventPublisherDep` |
| ① | `app/contexts/reputation/infrastructure/tasks.py`、`tests/contexts/reputation/application/test_apply_reputation.py` | DTO 来源改为 application.ports |
| ② | `app/contexts/qa/domain/question.py` | 新增 `ensure_open(action)`；`edit_title_body` 复用 |
| ② | `qa/application/{answer,accept,vote,comment}_use_case.py` | 6 处手写关闭态检查收敛为 `ensure_open(...)`；消息逐字不变 |
| ③ | `app/contexts/identity/interfaces/api/deps.py` | 收拢 `token_service`/`refresh_store`/`login_attempt_guard` + `build_register_use_case`/`build_login_use_case`；`get_current_user` 改走 `get_user_repository` |
| ③ | `app/contexts/identity/interfaces/api/routes.py` | 删除重复模块级单例与私有工厂，改从 deps 引入 |
| ③ | `app/contexts/reputation/interfaces/api/deps.py`（新增）、`routes.py` | 仓储装配入 deps，路由参数改 `ReputationLedgerRepo` |
| ④ | `app/platform/http/deps.py`（新增） | 共享 `SessionDep`（唯一声明处；worker 侧 `shared/engine.py` 不受影响） |
| ④ | `qa/interfaces/api/deps.py`、`identity/interfaces/api/deps.py` | 改 import 共享 `SessionDep` |
| ④ | `qa/interfaces/api/routes.py`、`identity/interfaces/api/routes.py` | `_question_response`/`_user_response` 收敛重复映射；`me()` 改 `CurrentUser` |
| ⑥ | `tests/test_architecture.py`（新增） | 五条 AST 架构断言（见文件 docstring） |

## 3. 方法与结果

| 检查项 | 命令 / 方法 | 结果 |
|:---|:---|:---|
| 静态检查 | `python -m ruff check app tests scripts` | **All checks passed** |
| 类型检查 | `python -m mypy app`（strict） | **95 文件 0 错误** |
| 契约防漂移 | `python scripts/export_openapi.py --check` | **一致**（17 paths / 19 ops 未变） |
| 应用装配冒烟 | `python -c "from app.main import create_app; create_app()"` | 通过（10 routes：4 文档 + 5 组 `_IncludedRouter` + `/health`） |
| 架构护栏 | `pytest -q tests/test_architecture.py` | **5 passed**（新规则对当前代码零告警） |
| 非 DB 用例 | `pytest -q tests/test_architecture.py tests/test_health.py tests/test_body_limit.py tests/test_text_validation.py tests/test_validation_handlers.py tests/test_jwt_security.py tests/contexts/{qa,identity,reputation}/domain` | **114 passed** |
| 用例级 + 契约 | `pytest -q tests/contexts/{qa,identity,reputation}/application tests/test_contract.py tests/test_architecture.py` | **80 passed** |
| 定向回归（本轮风险点） | `pytest -q` architecture + reputation interfaces + qa close/edit、answer/vote、accept/comment + identity auth、login_lockout | **59 passed**（115s） |
| 全量 pytest | `pytest -q`（Postgres 5432 + Redis 6379 已启动，`alembic current` = 46411f564ffa head） | **311 passed**（176s，0 failed / 0 skipped），含真库集成、acceptance、契约、架构 |
| 覆盖率门禁① | `pytest -m "not integration" --cov=app --cov-report=term-missing --cov-fail-under=70` | **189 passed / 122 deselected，TOTAL 81.12%**（阈值 70% 达标） |
| 覆盖率门禁② | `python -m coverage report --include="*/domain/*" --fail-under=90` | **domain 95%**（阈值 90% 达标；低覆盖仅限 Protocol `...` 方法体与适配器） |

## 4. 全量回归结论

原第 4 节的三项待补已全部执行并通过：

1. **声誉记账链路**：`test_reputation_api.py` 通过——`DeferredEventPublisher` 仍把 `.delay` 挂到 BackgroundTasks，eager 模式下投票/采纳记账正确；
2. **关闭态 409 全链路**：`test_close_edit_api.py` / `test_answer_vote_api.py` / `test_accept_comment_api.py` 通过——状态码与 7 条 detail 文案逐字未变；
3. **身份组合根搬家**：`test_auth_api.py` / `test_login_lockout_api.py` 通过——单例改由 deps 持有后登录/刷新/登出/锁定行为一致。

## 5. 遗留观察（非本轮引入，未处理）

- `app/contexts/{qa,identity}/domain/repository.py` 覆盖率 69%/67%：Protocol 方法体 `...` 被计为语句，属统计口径而非缺口；
- 7 条 Starlette/FastAPI 弃用 warning（`httpx` TestClient、`HTTP_422_UNPROCESSABLE_ENTITY`），既有依赖版本导致，未在本轮升级。

## 6. 批次 A（2026-11-05）：qa 仓储/路由拆文件

### 6.1 改动

| 目录 | 拆分结果 |
|:---|:---|
| `qa/infrastructure/` | 原 `repository.py` 删除；新增 `sql_expressions.py`（`net_votes_expr`）+ `question_repository.py`（含 `_question_net_votes`）/ `answer_repository.py` / `vote_repository.py` / `comment_repository.py` / `tag_repository.py` |
| `qa/interfaces/api/` | 原 `routes.py` 改为 re-export；新增 `questions.py`（提问/列表/详情/编辑/关闭/回答/两票/题评）/ `answers.py`（答评/采纳）/ `tags.py` / `_common.py`（`vote_on_target`、`create_comment_on_target`、`comment_response`、`vote_event_payload`） |
| 装配与测试 | `qa/deps.py` 改 5 条适配器 import；4 个集成测试文件共 5 条 import 同步，无兼容壳 |

### 6.2 契约回归（检查捕获，已修）

首轮拆分把 `vote_answer` 放进 `answers_router`，路径由
`/api/v1/questions/{question_id}/answers/{answer_id}/vote` 变成
`/api/v1/answers/{answer_id}/vote`；`export_openapi.py --check` 立即报漂移。
修正：按契约把该端点留在 questions 路由注册（它只是逻辑上属于回答动作）。
这说明 `--check` 门禁在纯移动重构中确实能兜住"路径搬家"这类隐性破坏。

### 6.3 结果

| 检查项 | 命令 | 结果 |
|:---|:---|:---|
| 静态检查 | `ruff check app tests scripts` | **All checks passed** |
| 类型检查 | `mypy app`（strict） | **104 文件 0 错误**（拆分新增 8 个模块） |
| 契约防漂移 | `export_openapi.py --check` | **一致**（17 paths / 19 ops 未变） |
| qa 全层 | `pytest -q tests/contexts/qa tests/test_architecture.py tests/test_contract.py` | **190 passed**（129s） |
| 全量回归 | `pytest -q` | **311 passed**（174s），基线不变 |

环境异常：首轮 qa 测试执行中 Docker Desktop 引擎退出，81 条集成用例全为 503；重启引擎与 db/redis 容器后复跑全绿，确认与代码无关。

## 7. 批次 D（2026-11-05）：shared 收尾

| 项 | 内容 |
|:---|:---|
| 迁移 | `shared/body_limit.py` → `platform/http/body_limit.py`；`shared/exception_handlers.py` → `platform/http/exception_handlers.py` |
| 保留 | `shared/` 仅 db / engine / redis / text_validation / errors（框架无关内核） |
| 同步 | `main.py` 与 `tests/test_body_limit.py` import 更新 |
| 清理 | 删除 `app/contexts/course`、`app/contexts/discovery` 的 8 个空 `__init__.py`（无 import 依赖） |
| 护栏 | 架构测试第 6 条（shared 禁 fastapi/starlette）、第 7 条（platform 仅 interfaces + main.py） |

结果：ruff 0 / mypy 96 文件 0 / 架构与 HTTP 组件 19 passed / OpenAPI 一致。

## 8. 批次 C1（2026-11-05）：DomainValidationError

- 新增 `app/shared/errors.py`：`DomainValidationError(ValueError)`；shared kernel 不 import 任何上下文。
- 17 处裸 `raise ValueError` 全量替换：qa domain 5、identity domain 4、shared 2、reputation domain 2、reputation application 1（`from exc` 保留）、qa/identity schemas 3。
- 行为等价依据：Pydantic validator 对 ValueError 子类同样转 422；worker `_RETRYABLE` 不含 ValueError 族，子类同样不重试。
- 新增 AST 断言 `test_no_bare_value_error_raised`（文本 grep 会误伤 `raise DomainValidationError`，故按 AST 判定）。
- 结果：ruff 0 / mypy 97 文件 0 / 无外部服务测试 171 passed / 全量 314 passed。

C2（删除路由 5 处 try/except 并把 DomainValidationError 注册为 422）未执行，保持两步走。

## 9. 批次 B（2026-11-05）：refresh/logout 用例化

| 项 | 内容 |
|:---|:---|
| 应用层 | 新增 `RefreshTokenUseCase`（解码→读用户→原子消耗→签发新对→存新 jti；保留先读后消耗的 503 可重试顺序）与 `LogoutUseCase`（解码失败静默成功，幂等 204） |
| 契约 | commands +`RefreshTokenCommand`/`LogoutCommand`；domain +`InvalidRefreshTokenError`；identity error_mapping 映射 401，detail 文案保持"刷新令牌无效或已过期/用户不存在/刷新令牌已失效" |
| 装配 | `identity/interfaces/api/deps.py` +`build_refresh_token_use_case` / `build_logout_use_case`；routes refresh/logout 只做命令构造与响应装配 |
| 测试 | 新增 `tests/contexts/identity/application/test_refresh_logout_use_cases.py` 10 条：轮换成功 / 旧 jti 复放 401 / 新 refresh 可继续轮换 / DB 读失败不消耗令牌 / 用户不存在 / jti 未知 / 归属不一致 / 解码失败 / logout 吊销 / logout 幂等 |

结果：ruff 0 / mypy 99 文件 0 / 身份用例+API+契约+架构 53 passed / 全量 324 passed / OpenAPI `--check` 一致。
