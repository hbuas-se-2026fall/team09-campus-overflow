# F18 内容举报与管理员后台 · 开发与测试台账

> 日期：2026-11-25 · 上下文：`qa`（零跨上下文写耦合，复用 F11 `UserSummaryReader` 公开展示名供给） · 依赖：F11（展示名回填）、F13（软删除与悬赏退还）、F15（RBAC `admin` 角色）
> 裁定：D1 举报目标严格限定 `question` 与 `answer`（严禁 `comment` 与 `comments.deleted_at`）；提交前校验目标未软删存在，含未软删检查 · D2 `uq_reports_pending_reporter_target`（`(reporter_id, target_type, target_id) WHERE status = 'pending'`）库级部分唯一索引防并发重复，驳回/处理后允许再次举报（409 `DuplicatePendingReportError`，绝不透传 `str(exc.orig)`） · D3 审核状态机与 3×2 处置策略矩阵（`ReportResolutionHandler` 策略注册，零修改 `CloseQuestionUseCase` / `DeleteQuestionUseCase` / `DeleteAnswerUseCase`，守 OCP）；`resolve_pending` 条件更新 `WHERE id = :id AND status = 'pending'` 在执行处置前抢占状态，任一步失败整事务回滚；锁序统一 `reports → questions → answers/bounties`
> 分支/工作区：`feat/f18-reports-admin`（独立评测子代理 Auditor #2.3-R2 终审 **PASS**，0 阻塞项）

## 一、交付范围

| 交付项 | 语义 |
|:--|:--|
| `POST /api/v1/reports` | 任何已认证用户（`student`/`teacher`/`ta`/`admin`）提交内容举报；目标仅允许 `question`/`answer`（其余 422）；校验目标存在且未软删（否则 404）；`reason` 5–500 安全文本（拒控制字符与 lone surrogate，`reject_unsafe_text`）；同一举报人对同一待处理对象重复举报返回 **409**（`detail: "您已举报过该内容，请等待管理员处理"`）；成功返回 **201 + `ReportResponse`** |
| `GET /api/v1/admin/reports` | 仅 `admin` 可访问（未登录 401，`student`/`teacher`/`ta` 403）；Query：`status`（默认 `pending`，传 `all` 查全状态）、`target_type`（可选 `question`/`answer`）、`page >= 1`（默认 1）、`page_size` 1..100（默认 20）；按 `(created_at DESC, id DESC)` 分页并批量 `IN` 去重回填 `reporter_name` 与 `resolved_by_name` |
| `POST /api/v1/admin/reports/{report_id}/resolve` | 仅 `admin` 可访问；请求体 `ResolveReportRequest`（`extra="forbid"`）：`action`（`dismiss`/`close_question`/`soft_delete`）、可选 `note`（1–500 安全文本，空白等价 `None`）；仅允许处置 `pending` 举报（不存在 404 `"举报不存在"`，已处置 409 `"该举报已被处理"`）；按 3×2 矩阵流转（`dismiss` 置 `dismissed` 且不校验目标存活；`close_question` 限问题、已关闭/含已采纳回答 409、作用于回答 422 `"仅问题类型举报支持关闭问题动作"`、成功联动 `refund_on_close`；`soft_delete` 对已采纳问题/回答 409、目标已删 404、删题联动 `refund_on_delete`） |
| 数据库迁移 | 迁移 `78debaff54c7`：新建 `reports` 表（`ck_reports_target_type` 仅允许 `('question', 'answer')`、`ck_reports_status` 仅允许 `('pending', 'resolved', 'dismissed')`、部分唯一索引 `uq_reports_pending_reporter_target` 及 `ix_reports_status_created`/`ix_reports_target`/`ix_reports_reporter_id` 索引，零跨上下文外键） |

明确不做（Non-Goals）：`comment` 目标举报与 `comments.deleted_at`；举报结果站内通知（零 `discovery` 改动）；用户封禁；修改 `CloseQuestionUseCase`/`DeleteQuestionUseCase`/`DeleteAnswerUseCase` 主干；前端页面修改。

## 二、六步法改动清单

| 步骤 | 文件 | 改动 |
|:--|:--|:--|
| 1 domain | `app/contexts/qa/domain/errors.py`、`report.py`（新建）、`repository.py` | 新增 `ReportNotFoundError`（404）、`DuplicatePendingReportError`（409）、`ReportAlreadyResolvedError`（409）、`InvalidReportActionError`（422）；定义 `ReportTargetType`/`ReportStatus`/`ReportAction`、`ReportReason`/`ResolutionNote`/`normalize_resolution_note`、`Report` 聚合；新增窄端口 `ReportRepository` Protocol |
| 2 application | `app/contexts/qa/application/commands.py`、`queries.py`、`create_report_use_case.py`（新建）、`list_reports_use_case.py`（新建）、`report_resolution_handlers.py`（新建）、`resolve_report_use_case.py`（新建） | 新增提交/查询/处置命令与查询 DTO；3×2 策略注册表 `build_report_resolution_handlers()` 隔离动作分支；复用 `BountyService` 同事务退还悬赏（守 OCP） |
| 3 infrastructure | `app/contexts/qa/infrastructure/models.py`、`report_repository.py`（新建）；`alembic/versions/78debaff54c7_add_reports_table_f18.py`（新建） | 声明 `ReportModel`（零跨上下文外键）；`SqlAlchemyReportRepository` 实现单源 `_apply_filters`、`23505` 部分唯一冲突翻译与条件 `UPDATE ... RETURNING`（区分 404/409）；生成并审核迁移 `78debaff54c7` |
| 4 interfaces | `app/contexts/qa/interfaces/api/error_mapping.py`、`deps.py`、`schemas.py`、`reports.py`（新建）、`routes.py`；`app/main.py` | 注册 4 个异常映射；新增 `get_report_repository`/`ReportRepo` 与严格 schema（`extra="forbid"`）；挂载 `reports_router`（`/api/v1/reports`）与 `admin_reports_router`（`/api/v1/admin/reports*`），批量 `IN` 回填展示名 |
| 5 tests | `tests/contexts/qa/{domain,application,infrastructure,interfaces}/`、`tests/test_contract.py` | 新建 `test_report.py`（4 单测）、`test_report_use_cases.py`（3 综合单测）、`test_reports_routes_unit.py`（路由单测）、`test_report_repository.py`（PG 约束与并发条件更新）、`test_reports_api.py`（RBAC + 全 3×2 矩阵 + `asyncio.gather` 并发）；`test_contract.py` 升至 `41 paths / 48 operations` |
| 6 收口 | `openapi.json`、本台账、`docs/PROGRESS.md`、`docs/plan/f-engineering-standard.md`、`README.md`、`docs/api/api-contract-notes.md` | 重导出契约过 `--check`，完成阶段 C（`v1.2.0`）全量 `pytest -m integration` 与 5 份文档同步 |

### 关键设计与人工审核记录
- **迁移人工审核**：`alembic revision --autogenerate -m "add reports table f18"` 仅检出 `reports` 表、`ck_reports_target_type`/`ck_reports_status` 检查约束与 4 个索引（含 `postgresql_where=text("status = 'pending'")` 部分唯一索引，零多余变更）；`downgrade()` 按逆序删索引后 `drop_table("reports")`。
- **OCP 与并发死锁防护**：`ResolveReportUseCase` 通过 `ReportRepository.resolve_pending()` 先以 `UPDATE reports SET ... WHERE id = :id AND status = 'pending' RETURNING *` 抢占待处理状态，再派发至对应 `ReportResolutionHandler`（`reports → questions → answers/bounties` 无环锁序），目标不可关闭/不可删除（409/404）或非法组合（422）时抛异常触发整事务回滚，原有举报保持 `pending`。

## 三、门禁与实测证据（2026-11-25）

| 检查项 | 命令 | 结果 |
|:--|:--|:--|
| Lint | `.venv\Scripts\ruff.exe check .` | `All checks passed!`（0 违规） |
| 严格类型检查 | `.venv\Scripts\mypy.exe app` | `Success: no issues found in 183 source files` |
| 契约导出与防漂移 | `.venv\Scripts\python.exe scripts/export_openapi.py --check` | `openapi.json 与当前代码一致`（**41 paths / 48 operations**） |
| 架构 + 契约测试 | `.venv\Scripts\pytest.exe tests/test_architecture.py tests/test_contract.py -q` | **20 passed**（4.54s，8 条 AST 护栏 0 违规） |
| CI 单元回归 + 覆盖率 | `.venv\Scripts\pytest.exe -m "not integration" --cov=app --cov-report=term-missing --cov-fail-under=70 -q` | **479 passed**, 239 deselected（17.97s）；TOTAL **84.08%** |
| 核心聚合覆盖率 | `.venv\Scripts\python.exe -m coverage report --include="*/domain/*" --fail-under=90` | **94%**（`qa/domain/{report,errors}.py` 均 **100%**） |
| 隔离库迁移往返 | 独立临时库 `campus_mig_test` 执行 `f18_mig_roundtrip.py`（`upgrade head → downgrade -1 → upgrade head → check` + 表/约束/索引断言 + `DROP DATABASE`） | `78debaff54c7 (head)` → `13a011cb2db6` → `78debaff54c7 (head)`；`No new upgrade operations detected.`；临时库已销毁 |
| 共享库备份与升级 | `docker exec campusoverflow-db-1 pg_dump -U campus campus > D:\a_work\_archive\db_backups\campus_pre_f18.sql`；`alembic upgrade head` / `current` / `check` | 备份 **10,434,012 B**（D 盘）；共享库平滑升至 `78debaff54c7 (head)`，`No new upgrade operations detected.` |
| F18 定向集成 + 并发 2 轮 | `pytest tests/contexts/qa/infrastructure/test_report_repository.py tests/contexts/qa/interfaces/test_reports_api.py -v`（连续 2 轮，含 `fix/f18-report-target-preview` 增量） | 第 1 轮 **5 passed**（25.81s）/ 第 2 轮 **5 passed**（26.08s）（前期 `feat/f18-reports-admin` 合入前 Auditor 复核 4 passed × 2） |
| 阶段 C（`v1.2.0`）全量真库集成回归 | `.venv\Scripts\pytest.exe -m integration -q`（真实 PG `15432` + Redis `16379`）；Auditor 另独立复测跨模块 **28 passed**（113.83s） | **238 passed**, 479 deselected（441.11s / 0:07:21，F18 基线收口；F01–F18 合计 **717 passed**） |
| 真实进程端到端冒烟 | 真实 `uvicorn app.main:app`（`127.0.0.1:18128`）连真实 PG `15432` + Redis `16379`（含目标预览字段全链路验证） | **41 HTTP 请求全绿**（含 RBAC 401/403、默认 `pending` 与 `?status=all` 200、`?status=invalid` 422、重复举报 409、`dismiss`/再报、回答 `close_question` 422、`soft_delete` 后仍带出 `target_body`/`target_question_id`/`target_title`/`target_is_deleted=True`、带悬赏问题关/删退分及主干回归），0 HTTP 500 / 0 Traceback，测试数据 0 残留 |

### 2026-11-26 增量补齐：`fix/f18-report-target-preview`（零迁移）
- **背景**：前端联调后台审核列表时，回答举报需要直接展示被举报回答正文（`target_body`）、所属问题 ID（`target_question_id`）及问题标题（`target_title`）与软删状态（`target_is_deleted`）。
- **实现**：`qa/domain/repository.py` 新增 `ReportTargetPreview` 与 `ReportTargetPreviewReader`（ISP）；`qa/infrastructure/report_target_preview_reader.py` 实现 `SqlAlchemyReportTargetPreviewReader`（空输入 0 SQL，混合页至多 2 条 `IN` 查询，不按 `deleted_at` 过滤以便历史工单回溯）；`qa/interfaces/api/{deps,schemas,reports}.py` 注入依赖并统一在提交/列表/处置响应回填。
- **测试补齐**：`tests/test_contract.py`、`test_reports_routes_unit.py`（含缺失目标回退 `None`）、`test_report_repository.py`（`test_report_target_preview_reader_sql_count_and_soft_delete` 实测 0 SQL / <=2 SQL）及 `test_reports_api.py`（断言问题/回答预览与软删后保留正文）。

- **独立评测复核（2026-11-26）**：`F18 Target Preview Auditor` 独立验收 **`PASS`**（0 阻塞项）—— `ruff` 0、`mypy` 183 文件 0、架构+契约 20 passed（5.99s）、CI 单测 479 passed（TOTAL 84.08%，domain 94%）、`test_report_repository.py + test_reports_api.py` 连续 2 轮 **5 passed × 2**（26.79s / 26.91s）、真实 `uvicorn`（`127.0.0.1:18131`）**37 HTTP 请求**（含父问题软删连带子回答 `target_is_deleted=True` 与 `?status=all` 历史原正文回溯）零 500 / 零 Traceback / 0 残留。

### 测试数据知识来源（遵循真实知识测试数据规范）
- PostgreSQL 部分唯一索引（Partial Indexes，`https://www.postgresql.org/docs/current/indexes-partial.html`）与 MVCC 行锁并发可见性（`https://www.postgresql.org/docs/current/mvcc.html`）。

## 四、测试覆盖

| 文件 | 改动 | 覆盖点 |
|:--|:--|:--|
| `tests/contexts/qa/domain/test_report.py` | +4 单测（新建） | `ReportReason`/`ResolutionNote` 清洗与拒绝控制字符、`Report.file()` 默认态及非法枚举值校验 |
| `tests/contexts/qa/application/test_report_use_cases.py` | +3 综合单测（新建） | 提交举报 404（含软删过滤）、分页列表筛选与展示名回填、完整 3×2 处置矩阵（含 404/409/422 回滚与悬赏退还） |
| `tests/contexts/qa/interfaces/test_reports_routes_unit.py` | 新建路由单测 | 401/403/404/409/422 路由错误映射、`extra="forbid"` 拒绝多余字段、默认 `pending` / `status=all` / `resolved` / `dismissed` 与展示名批量回填 |
| `tests/contexts/qa/infrastructure/test_report_repository.py` | +1 集成（新建） | 部分唯一索引 `23505` 转译（不透传原 SQL）、`dismissed` 后重报放行、库级 `CHECK` 拒收 `comment`、`resolve_pending` 并发条件更新区分 404/409 |
| `tests/contexts/qa/interfaces/test_reports_api.py` | +3 集成（新建，含并发） | 真实 PG+Redis 全角色 RBAC 与完整 3×2 处置矩阵（含带悬赏问题关贴退分、软删全链路过滤）；`asyncio.gather` 6 并发重复举报与 6 并发管理员同时处置；`GET /api/v1/admin/reports` 默认 `pending`、`?status=all`、组合筛选与 F11 展示名回填 |
| `tests/test_contract.py` | 同步契约断言 | 更新 `_FAMILIES["reports"]`、总路径/操作数为 `41 paths / 48 operations`，新增 `GET /api/v1/admin/reports` `status` 参数默认值及 F18 请求/响应 schema 校验 |

## 五、DoD 勾选

- [x] 六步法落地，严守 F18 白名单边界与 OCP（零修改 `CloseQuestionUseCase`/`DeleteQuestionUseCase`/`DeleteAnswerUseCase`，`test_architecture.py` 8 条 AST 护栏全绿）
- [x] 迁移 `78debaff54c7` 已人工审核并在独立临时库 `campus_mig_test` 完成 `up → down → up → check` 往返；共享库已先备份至 D 盘再 `upgrade head` 零漂移
- [x] 单元 + 定向集成与并发 2 轮 + 阶段 C（`v1.2.0`）全量真库集成 **238 passed** + 真实 Uvicorn 冒烟 **40 HTTP 请求**实测通过
- [x] `openapi.json` 与 `tests/test_contract.py` 已同步且过 `--check`
- [x] 5 份文档（本台账、`docs/PROGRESS.md`、`docs/plan/f-engineering-standard.md`、`README.md`、`docs/api/api-contract-notes.md`）口径一致
- [x] 独立评测子代理终审通过（Auditor #2.3-R2：`PASS`，0 阻塞项）
- [x] 经用户批准提交推送 `feat/f18-reports-admin`、提 PR 及远端 CI 全绿后合入 `main`（F18 基线 PR #10 `8159f70` 已合入；`fix/f18-report-target-preview` 增量补齐待用户批准提交 PR）
