# F14 评论二级回复 · 开发与测试台账

> 日期：2026-11-21 · 上下文：`qa` + `discovery` · 依赖：F04（站内通知中心）、F11（公开展示名）、F12（编辑回答返回评论）、F13（软删除与单根锁序）
> 裁定：D1 响应形态（详情与评论列表保持按 `created_at ASC, id ASC` 平铺返回，`CommentResponse` 增量暴露可空 `parent_id`，100% 向后兼容）· D2 层级与校验（`CommentRequest` 增可选 `parent_id`，保留 `extra="forbid"`；父评论不存在 404 `"评论不存在"`；跨宿主 `(target_type, target_id)` 422 `"父评论不属于当前对象"`；回复二级评论 422 `"评论仅支持二级回复，不可回复二级评论"`；允许回复自己的一级评论）· D3 并发锁序与库级兜底（沿用 F13 `Question(for_update=True)` 单根无环锁序；`CommentRepository` 最小扩展 `get_by_id`；`comments.parent_id` 配 `fk_comments_parent_id` RESTRICT、`ix_comments_parent_id`、`ck_comments_no_self_parent`）· D4 通知升级（`discovery` 新增 `NotificationType.COMMENT_REPLIED` 与 `NotificationTargetType.COMMENT`，零迁移；二级回复向父评论作者发 `comment_replied`、向不同宿主作者发 `comment_created`，同人去重只发 1 条 `comment_replied`，自操作跳过）
> 分支/工作区：`feat/f14-comment-replies`（已通过 Auditor #1.1 独立验收 PASS，已批准提交推送待 PR 合入 `main`）

## 一、交付范围

| 交付项 | 语义 |
|:--|:--|
| `POST /api/v1/questions/{question_id}/comments` | 请求体 `CommentRequest` 新增可选 `parent_id: UUID \| None = None`（`extra="forbid"`）；成功 **201** 返回带 `parent_id` 的 `CommentResponse`；父评论不存在 **404**；跨宿主/三级回复 **422**；问题已关闭 **409**；问题已软删 **404** |
| `POST /api/v1/answers/{answer_id}/comments` | 同上；沿用“先读 Answer → 锁父 Question → 锁后重读 Answer → 校验未关闭 → 校验父评论”锁序，闭环删答/删题/关贴并发窗口 |
| 详情与编辑回答评论响应 | `GET /api/v1/questions/{question_id}` 与 `PATCH /api/v1/answers/{answer_id}` 的 `comments[]` 保持按 `created_at ASC, id ASC` 平铺返回，每条增量携带 `parent_id` |
| 站内通知联动（`discovery`） | 新增 `NotificationType.COMMENT_REPLIED = "comment_replied"` 与 `NotificationTargetType.COMMENT = "comment"`（`notifications` 列为 `String(20)`/`String(10)`，**零迁移**）；二级回复同事务通知父评论作者（`comment_replied`, `target_type="comment"`, `target_id=parent.id`, `question_id=所属问题ID`）与不同宿主作者（`comment_created`），同人去重且自操作跳过 |
| 数据库迁移 | `alembic/versions/609aeba713d3_add_comment_parent_id_f14.py`（`comments` 新增可空 `parent_id`、`fk_comments_parent_id` `ON DELETE RESTRICT`、`ix_comments_parent_id`、`ck_comments_no_self_parent`） |

明确不做（Non-Goals）：评论编辑/删除、三级及以上嵌套回复、评论点赞、响应改为嵌套树结构、`frontend/` 改动。

## 二、六步法改动清单

| 步骤 | 文件 | 改动 |
|:--|:--|:--|
| 1 domain | `app/contexts/qa/domain/errors.py`、`comment.py`、`repository.py`；`app/contexts/discovery/domain/notification.py` | 新增 `CommentNotFoundError`；`Comment` 增 `parent_id`、自引用 `__post_init__`、`validate_parent()` 与 `write(..., parent=...)`（`CommentCreated` 同步带 `parent_id`）；`CommentRepository` 最小扩展 `get_by_id`；`discovery` 新增 `NotificationType.COMMENT_REPLIED` 与 `NotificationTargetType.COMMENT` |
| 2 application | `app/contexts/qa/application/commands.py`、`comment_use_case.py` | `CreateCommentCommand` 增可选 `parent_id`；`CreateCommentUseCase` 拆分为 `_resolve_host` / `_resolve_parent` / `_notify`，严格守 F13 锁序并落实 D2 校验与 D4 去重通知 |
| 3 infrastructure | `app/contexts/qa/infrastructure/models.py`、`comment_repository.py`；`alembic/versions/609aeba713d3_add_comment_parent_id_f14.py`（新建） | `CommentModel` 增 `parent_id`、显式外键 `fk_comments_parent_id`（`RESTRICT`）、索引 `ix_comments_parent_id` 与检查约束 `ck_comments_no_self_parent`；仓储抽取 `_to_domain` 并实现 `get_by_id`（`populate_existing=True`）；人工审核迁移补齐显式约束名与 `CHECK` 约束 |
| 4 interfaces | `app/contexts/qa/interfaces/api/error_mapping.py`、`schemas.py`、`_common.py`、`questions.py`、`answers.py`；`app/contexts/discovery/interfaces/api/schemas.py` | 注册 `CommentNotFoundError → 404`；`CommentRequest`/`CommentResponse` 增可空 `parent_id`；`_common.py` 透传 `parent_id`；路由零业务校验、零 `try/except` |
| 5 tests | 领域/用例/fake/仓储/API 并发/契约测试 | 同步 4 个 `FakeCommentRepository` 实现 `get_by_id`；新建 `tests/contexts/qa/domain/test_comment.py`（+5）、`tests/contexts/discovery/domain/test_notification.py`（+3）、`tests/contexts/qa/infrastructure/test_comment_replies_repository.py`（+2 集成）、`tests/contexts/qa/interfaces/test_comment_replies_api.py`（+3 集成含 `asyncio.gather` 并发实证）；扩展 `test_accept_comment_use_cases.py`（+4）、`test_notification_hooks.py`（+3）、`test_accept_comment_api.py`（key-set 同步）、`tests/test_contract.py`（+1 契约断言） |
| 6 收口 | `openapi.json`、本台账、`docs/PROGRESS.md`、`docs/plan/f-engineering-standard.md`、`README.md`、`docs/api/api-contract-notes.md` | 重导出契约过 `--check`（`31 paths / 36 operations`），5 份文档口径一致 |

### 关键设计与人工审核记录
- **迁移人工审核发现并修复 2 处 autogenerate 缺陷**：① `alembic --autogenerate` 为自引用外键生成了匿名 `None`，在 PostgreSQL 下执行 `downgrade` 会失败 → 已在模型与迁移脚本显式命名 `fk_comments_parent_id`；② autogenerate 默认忽略新增的 `CheckConstraint` → 已人工补齐 `op.create_check_constraint("ck_comments_no_self_parent", ...)` 与对称 `downgrade`。
- **单根无环锁序与并发安全**：题评锁 `Question(for_update=True)` 后再验父评论；答评先读 `Answer`、锁父 `Question(for_update=True)`、重读 `Answer`、验开放态后再验父评论，确保关贴×二级回复、删题×二级回复、删答×二级回复严格线性化，杜绝孤儿回复。
- **包原则与 SOLID 守门**：`qa` 与 `discovery` 继续保持零跨层耦合（`NotificationWriter` 窄 Protocol + 原始类型），`CommentRepository` 仅新增 `get_by_id`（ISP），4 处 `FakeCommentRepository` 与真仓储严格对齐（LSP），单函数 < 30 行且嵌套 ≤ 2 层（CCP/SRP）。

## 三、门禁与实测证据（2026-11-21 / 2026-11-22）

| 检查项 | 命令 | 结果 |
|:--|:--|:--|
| Lint | `.venv\Scripts\ruff.exe check .` | `All checks passed!`（0 违规） |
| 严格类型检查 | `.venv\Scripts\mypy.exe app` | `Success: no issues found in 146 source files` |
| 契约导出与防漂移 | `.venv\Scripts\python.exe scripts/export_openapi.py --check` | `openapi.json 与当前代码一致`（**31 paths / 36 operations**） |
| 架构 + 契约测试 | `.venv\Scripts\pytest.exe tests/test_architecture.py tests/test_contract.py -q` | **16 passed**（8 条 AST 护栏 0 违规） |
| CI 单元回归 + 覆盖率 | `.venv\Scripts\pytest.exe -m "not integration" --cov=app --cov-report=term-missing --cov-fail-under=70 -q` | **382 passed**, 218 deselected；TOTAL **82.87%** |
| 核心聚合覆盖率 | `.venv\Scripts\python.exe -m coverage report --include="*/domain/*" --fail-under=90` | **94%**（`qa/domain/comment.py`、`qa/domain/errors.py`、`discovery/domain/notification.py` 均 **100%**） |
| 隔离库迁移往返 | 独立临时库 `campus_mig_test` 执行 `upgrade head → current → downgrade -1 → current → upgrade head → check` + 库对象核验 + `DROP DATABASE` | `609aeba713d3 (head)` → `c90363e3c1fb` → `609aeba713d3 (head)`；`No new upgrade operations detected.`；核验 `ck_comments_no_self_parent`、`fk_comments_parent_id (RESTRICT)`、`ix_comments_parent_id` 全部到位并销毁临时库 |
| 共享库备份与升级 | `docker exec campusoverflow-db-1 pg_dump -U campus campus > D:\a_work\_archive\db_backups\campus_pre_f14.sql`；`alembic upgrade head` / `current` / `check`（未对共享库运行 `downgrade`） | 备份文件 **8,644,392 B**（D 盘非 C 盘）；共享库平滑升至 `609aeba713d3 (head)`，`No new upgrade operations detected.` |
| F14 定向集成 + 并发 2 轮 | `.venv\Scripts\pytest.exe tests/contexts/qa/infrastructure/test_comment_replies_repository.py tests/contexts/qa/interfaces/test_comment_replies_api.py -q`（连续 2 轮，PG `127.0.0.1:15432` + Redis `127.0.0.1:16379`） | Builder：第 1 轮 **5 passed**（17.81s）/ 第 2 轮 **5 passed**（17.91s）；Auditor #1.1 复测：**5 passed × 2**（24.63s / 23.88s） |
| 跨模块关联回归（Auditor #1.1） | `test_accept_comment_api.py`、`test_notification_api.py`、`test_edit_answer_api.py`、`test_f11_display_name_and_profile_api.py`、`test_accept_comment_repository.py`、`test_notification_repository.py` | **12 + 16 = 28 passed** |
| 真实进程端到端冒烟（Auditor #1.1） | 真实 `uvicorn app.main:app`（`127.0.0.1:18124` 连 PG `15432` + Redis `16379`）覆盖 F14 全路径 + 存量核心主干 | **54 HTTP 请求全绿**，日志零 500 / 零未捕获 Traceback，临时数据 0 残留 |
| 全量集成套件（`pytest -m integration`） | — | **按用户裁定延至大板块 1（F14–F15 / `v1.1.0`）收口时统一执行** |

### 测试数据知识来源（遵循真实知识测试数据规范）
- Operating Systems: Three Easy Pieces（MLFQ 调度、Mesa vs Hoare 条件变量、锁与死锁避免）：`https://pages.cs.wisc.edu/~remzi/OSTEP/`
- PostgreSQL Concurrency Control（MVCC、悲观行锁 `SELECT FOR UPDATE`）：`https://www.postgresql.org/docs/current/mvcc.html`

## 四、测试覆盖

| 文件 | 改动 | 覆盖点 |
|:--|:--|:--|
| `tests/contexts/qa/domain/test_comment.py` | +5 单测（新建） | 一级/二级评论创建与事件 `parent_id`、自回复允许、三级回复 422、跨宿主 `target_id`/`target_type` 422、自引用 `__post_init__` 422 |
| `tests/contexts/discovery/domain/test_notification.py` | +3 单测（新建） | `NotificationType.COMMENT_REPLIED`、`NotificationTargetType.COMMENT`、`build_notification` 与非法枚举拒绝 |
| `tests/contexts/qa/application/test_accept_comment_use_cases.py` | +4 单测 + Fake 同步 | 题评/答评二级回复与 `for_update=True` 锁序、父评论缺失 404、跨宿主/三级 422、关贴先拦截 409 |
| `tests/contexts/qa/application/test_notification_hooks.py` | +3 单测 + Fake 同步 | 三方双发（`comment_replied` + `comment_created`）、宿主作者==父评作者同人去重只发 1 条 `comment_replied`、自回复与答评路由 |
| `tests/contexts/qa/application/test_close_edit_use_cases.py` & `test_question_query_use_cases.py` | Fake 同步 | `FakeCommentRepository.get_by_id` LSP 对齐 |
| `tests/contexts/qa/infrastructure/test_comment_replies_repository.py` | +2 集成（新建） | `get_by_id` 存在/不存在、平铺时间正序、库级 `ck_comments_no_self_parent` 与 `fk_comments_parent_id (RESTRICT)` 实证 |
| `tests/contexts/qa/interfaces/test_comment_replies_api.py` | +3 集成（新建） | 全校验矩阵（含详情/编辑回答平铺、`extra=forbid`、关贴 409、F13 软删全隐藏）、F04 通知去重端到端、`asyncio.gather` 双顺序并发实证（关贴/删题/删答 × 二级回复） |
| `tests/contexts/qa/interfaces/test_accept_comment_api.py` | 同步 | `CommentResponse` 白名单键集合新增 `parent_id` |
| `tests/test_contract.py` | +1 契约测试 | 断言 `CommentRequest`/`CommentResponse` 暴露可空 UUID `parent_id` 且保留 `additionalProperties: false` |

## 五、DoD 勾选

- [x] 六步法落地，仅触及 F14 范围，`test_architecture.py` 8 条 AST 护栏全绿
- [x] 迁移 `609aeba713d3` 已人工审核并完成独立临时库 `campus_mig_test` `up → down → up → check` 往返验证；共享库先备份 D 盘再 `upgrade head` 零漂移
- [x] 单元 + 定向仓储/API 集成 + 并发 2 轮测试写入 `tests/` 并实测通过（全量集成按用户裁定延至大板块 1 收口统一执行）
- [x] `openapi.json` 与 `tests/test_contract.py` 已同步且过 `--check`
- [x] 5 份文档（本台账、`docs/PROGRESS.md`、`docs/plan/f-engineering-standard.md`、`README.md`、`docs/api/api-contract-notes.md`）口径一致
- [x] 独立评测子代理（Auditor #1.1）5 维终审 + 真实 Uvicorn 冒烟 PASS（0 阻塞 / 0 警告）
- [ ] 经用户批准推送 `feat/f14-comment-replies` 提 PR 及 Actions 全绿
