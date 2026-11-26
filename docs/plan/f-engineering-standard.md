# CampusOverflow · F 系列工程标准与研发规范（F01–F20）

> 适用范围：阶段 3 增量扩展与阶段 4 上线交付的全部 `Fxx` 特性工程（已交付 `F01–F18`，规划中 `F19–F20` 及顺接 `F21`）。
> 上位约束：[GOALS.md](../../GOALS.md)、[.github/workflows/ci.yml](../../.github/workflows/ci.yml)、[tests/test_architecture.py](../../tests/test_architecture.py)、[docs/sprint/review-checklist.md](../sprint/review-checklist.md)。

---

## 一、工程铁律

1. **自主实现边界**：课程实践项目，严禁参考或复制任何开源项目代码；设计仅依据课程规范、项目 ADR 与团队推理。
2. **证据优先原则**：任何“通过 / 完成”结论必须附带本次实测命令与真实输出；未实际运行的检查一律标明“未验证”，禁止放宽门禁阈值（如删测试、改 `mypy --strict`、降低覆盖率要求）。
3. **语言规范**：代码注释、文档、提交信息、测试台账使用中文；代码标识符（包名、类名、方法名、变量名、字段名）使用英文。
4. **单特性小步闭环**：每个 `Fxx` 必须独立走完“六步法 + 门禁 + 台账 + 契约校验”，再进入下一个 `Fxx`；禁止跨特性大杂烩提交。

---

## 二、硬性架构护栏（机器强制）

由 [tests/test_architecture.py](../../tests/test_architecture.py) 通过 AST 静态扫描在每次 CI 中强制断言（共 8 条）：

| 编号 | 规则 | 说明 |
|:---|:---|:---|
| A1 | `domain` 零框架且不向外依赖 | 禁止 import `fastapi` / `starlette` / `sqlalchemy` / `redis` / `celery` / `asyncpg`，也不得 import 同上下文 `application` / `infrastructure` / `interfaces` |
| A2 | `application` 不依赖适配器 | 禁止 import `.infrastructure` 或 `.interfaces` |
| A3 | `infrastructure` 不入站 | 禁止 import `.interfaces` |
| A4 | 跨上下文边界受控 | 跨上下文 `import` 仅允许发生在 `interfaces` 层，且目标限于对方 `interfaces` 或对方 `application/ports.py`（已发布语言） |
| A5 | `reputation` 对 `qa` 零耦合 | `reputation` 任何层禁止 `import app.contexts.qa*`，仅通过事件载荷通信 |
| A6 | `app/shared` 保持 Web 框架无关 | 允许 SQLAlchemy / Redis 内核，禁止 `fastapi` / `starlette` |
| A7 | `app/platform` 仅边界可用 | 仅 `app/*/interfaces` 与 `app/main.py` 可 import |
| A8 | 禁止裸 `raise ValueError` | 输入校验统一抛出 `DomainValidationError`（[app/shared/errors.py](../../app/shared/errors.py)），由全局处理器统一映射 422 |

---

## 三、单特性标准研发流程（六步法 SOP）

每个 `Fxx` 落地均须严格按以下 6 步依次推进：

### Step 0：需求裁定与边界声明
- 明确归属限界上下文、依赖的前置 `Fxx`、涉及端点及核心业务口径。
- 为争议点编号裁定（如 `D1` / `D2`），并在台账显式写出 **“明确不做（Non-Goals）”**，防止范围蔓延。

### Step 1：`domain` 层建模
- **值对象**：使用 `frozen dataclass`，全部规范化与校验逻辑收敛在 `__post_init__` 并抛 `DomainValidationError`；文本输入复用 `reject_unsafe_text`（拒绝控制字符与 lone surrogate）。
- **聚合根**：保持刻意收小，不变式优先在聚合方法（如 `ensure_open()`）中收口。
- **仓储端口**：在 `<ctx>/domain/repository.py` 定义 `Protocol`；写路径需要行级写锁时统一使用关键字参数 `*, for_update: bool = False`，不复制平行方法。

### Step 2：`application` 层编排 + 单元测试先行
- 在 `commands.py` / `queries.py` 定义命令/查询 DTO，用例（UseCase）只依赖领域层与 `Protocol` 端口。
- 写路径涉及竞态校验（如悬赏、关闭、采纳）时，必须在同一事务内显式以 `for_update=True` 读取聚合并完成状态/前置条件检查。
- 跨存储操作（如 Redis + DB）遵循“可重入读先于不可逆消耗”。
- 同步编写基于 fake 仓储的单元测试（覆盖正常路径、权限/状态分支、边界值）。

### Step 3：`infrastructure` 层实现 + 迁移纪律
- 仓储适配器实现领域端口；SQL 表达式复用单源辅助函数（如 `net_votes_expr`、`escape_like`）。
- 并发敏感写路径**必须配备数据库级兜底**：
  - 唯一约束 / 部分唯一索引（如 `uq_question_bounties_open`）
  - 条件 `UPDATE ... WHERE`（原子状态迁移）
  - `CHECK` 约束（如 `balance >= 0`）
  - `ON CONFLICT DO NOTHING` 幂等插入
- 仓储层将驱动异常/约束冲突翻译为领域异常，严禁将 `str(exc.orig)` 原样透传给客户端。
- **Alembic 迁移纪律**：
  1. 若涉及表结构/索引变更，执行 `alembic revision --autogenerate` 生成脚本；
  2. **人工逐行审核**生成的迁移脚本（检查无误删列/索引漂移）；
  3. 验证 `upgrade` / `downgrade` 往返可执行后应用到目标库。

### Step 4：`interfaces/api` 层装配
- 路由保持薄壳：仅做参数绑定、命令/查询构造、调用 UseCase、组装响应 Schema；**路由内零业务校验分支与零兜底 `try/except`**。
- 新增领域异常统一在 `<ctx>/interfaces/api/error_mapping.py` 注册 HTTP 状态码映射（403 / 404 / 409 / 422 / 423）。
- 数据库会话依赖统一使用 `Depends(get_session, scope="function")`，确保事务提交完成后再发送 HTTP 响应。

### Step 5：全层级测试补齐
- **单元测试（进 CI，无 DB/Redis 依赖）**：`domain` 与 `application` 用例分支全覆盖。
- **集成测试（`@pytest.mark.integration`，真实 PG + Redis）**：
  - 覆盖真实 SQL 查询、分页与 `total` 同口径对账、迁移后完整请求链路；
  - 并发竞争场景必须补充 `asyncio.gather` 实证用例，断言终态唯一性与数据守恒；
  - 测试数据/Redis 状态需具备隔离与幂等性，重复运行多轮稳定通过。
- **契约测试**：若新增/变更路径，必须同步更新 [tests/test_contract.py](../../tests/test_contract.py) 的 `_FAMILIES` 清单及 `paths` / `operations` 计数断言。
- **前端测试（若涉及前端）**：组件测试与 Vitest 单测全过（[frontend/vite.config.ts](../../frontend/vite.config.ts) 已配置 `fileParallelism: false` 与 `testTimeout: 20000`，避免低配 Runner 并行卡滞）。

### Step 6：契约导出、门禁核验与文档收口
- 重新导出契约并防漂移核验：
  ```powershell
  python scripts/export_openapi.py
  python scripts/export_openapi.py --check
  ```
- 新增/更新台账 `docs/test/Fxx-<slug>.md`；同步更新 [docs/PROGRESS.md](../PROGRESS.md) 变更记录、[docs/api/api-contract-notes.md](../api/api-contract-notes.md)（接口语义变化时）及 [README.md](../../README.md)（端点/指标变化时）。

---

## 四、团队评审清单与 CI 质量门禁

### 1. 代码评审清单（14 条基线）
合并前必须逐条核对 [docs/sprint/review-checklist.md](../sprint/review-checklist.md)（v1.0）：
- **A. 并发与一致性**：先读后写库级兜底；条件 UPDATE 分支语义回归；跨存储操作顺序安全。
- **B. 异常与信息安全**：禁回显 `str(exc.orig)`；连接故障 503 vs 数据约束 400 分层覆盖。
- **C. 契约与单源**：OpenAPI `--check` 一致；规则/归一逻辑不跨层双写。
- **D. 迁移与数据库**：`down → up` 往返验证；`autogenerate` 人工审核后才 `upgrade`。
- **E. 事件与异步任务**：事件载荷自足（上游零回查）；Celery 独立 `NullPool` 引擎 + `acks_late` + 幂等；失败语义写明。
- **F. 校验与测试**：三层输入校验齐备（Schema → VO → 全局处理器）；测试夹具清理干净。

### 2. 自动化门禁清单（对应 [.github/workflows/ci.yml](../../.github/workflows/ci.yml)）

| 端 | 检查项 | 命令 | 合格标准 |
|:---|:---|:---|:---|
| 后端 | Lint 检查 | `ruff check .` | 0 违规 |
| 后端 | 严格类型检查 | `mypy app` | `--strict` 0 错误 |
| 后端 | CI 单元 + 总覆盖率 | `pytest -m "not integration" --cov=app --cov-report=term-missing --cov-fail-under=70` | 全绿，总覆盖率 ≥ 70% |
| 后端 | 核心聚合覆盖率 | `python -m coverage report --include="*/domain/*" --fail-under=90` | `domain` 层 ≥ 90% |
| 后端 | OpenAPI 契约防漂移 | `python scripts/export_openapi.py --check` | 与 [openapi.json](../../openapi.json) 一致 |
| 后端 | 集成验证（本地 PG+Redis） | `pytest -m integration` | 全绿（本地 Docker 环境可用时必跑） |
| 前端 | 锁文件校验 | `pnpm install --frozen-lockfile` | 锁文件无漂移 |
| 前端 | 类型检查 | `pnpm run typecheck` | `tsc -b --pretty false` 0 错误 |
| 前端 | 测试套件 | `pnpm run test` | `vitest run` 全部通过 |
| 前端 | 生产构建 | `pnpm run build` | `vite build` 成功 |
| 前端 | Lint 检查 | `pnpm run lint` | `oxlint` 0 警告 0 错误 |

### 3. 提交、环境与分支规范
- **提交规范**：遵循 Conventional Commits，按特性或职责独立拆分提交；遵循 [.github/pull_request_template.md](../../.github/pull_request_template.md)。
- **Windows 本地端口避让**：[.env.example](../../.env.example) 与 [docker-compose.yml](../../docker-compose.yml) 已参数化 `DB_PORT` / `REDIS_PORT`，提交代码前可用 `.\scripts\launcher\campus_launcher.ps1 -Check` 自检；严禁将个人 `.env` 提交入库。
- **远端 CI 注意**：`.github/workflows/ci.yml` 仅监听 `push(main)` 与 `pull_request`；合并 `main` 后需确认 `ci` 与 `frontend` 双 Job 全绿。

---

## 五、F01–F20 全量工程总表

### 1. 已交付基线（F01–F18）

| 编号 | 名称 | 上下文 | 关键交付与修补 | 迁移 | 台账 |
|:---|:---|:---|:---|:---|:---|
| **F01** | 问题多维筛选（US-Q07） | `qa` | `tag`（≤5 去重 AND）、`status`、`created_from/to` 闭区间筛选；`_apply_filters` 与 `COUNT` 同口径 | 无 | [F01-question-filter.md](../test/F01-question-filter.md) |
| **F02** | 全文搜索基础版 | `qa` | `QuestionFilter.q`（≤100 字，拒换行/控制字符）+ `escape_like` + 标题/正文 `ILIKE` | 无 | [F02-full-text-search.md](../test/F02-full-text-search.md) |
| **F03** | 相关问题推荐 | `qa` | `GET /api/v1/questions/{id}/related`（标签重合→净票→时间→id 全序，排除自身） | 无 | [F03-related-questions.md](../test/F03-related-questions.md) |
| **F04** | 站内通知中心 | `discovery` + `qa` | 4 个通知端点；`notifications` 表与同事务写入；补齐 `payload.question_id` 跳转定位 | `82908edc9ebf` | [F04-notifications.md](../test/F04-notifications.md) |
| **F05** | 周/月/学期排行榜 | `reputation` | `GET /api/v1/leaderboard`（`Asia/Shanghai` 窗口 + `RANK()` 竞争排名）；修复测试时间基座隔离 | 无 | [F05-leaderboard.md](../test/F05-leaderboard.md) |
| **F06** | 用户徽章体系 | `qa` + `identity` | `GET /api/v1/users/{id}/badges`（回答数 / 采纳率 / 历史最长连续活跃天数） | 无 | [F06-badges.md](../test/F06-badges.md) |
| **F07** | 教师悬赏与个人积分 | `qa` | `POST/GET .../bounty` + `GET /api/v1/users/me/points`；`for_update` 行锁修并发；已采纳问题 409 拦截 | `29caa98ef40a` | [F07-bounty.md](../test/F07-bounty.md) |
| **F08** | 排行榜索引与热榜缓存（D5） | `reputation` | `reputation_ledgers` 增 `(occurred_at, user_id) INCLUDE (delta)` 覆盖索引；`GET /api/v1/leaderboard` 接入 Redis 短时缓存（TTL 60s，故障降级直查库） | `6360fb6b24dd` | [F08-leaderboard-cache.md](../test/F08-leaderboard-cache.md) |
| **F09** | 核心读路径性能与搜索索引升级 | `identity` + `qa` | `SqlAlchemyUserRepository` 合并为单条 4 步 `outerjoin`；`questions` 启用 `pg_trgm` 双 GIN 索引（`ix_questions_title_trgm`/`body_trgm`） | `ef84c7f8187e` | [F09-read-perf-and-trgm.md](../test/F09-read-perf-and-trgm.md) |
| **F10** | 校园资料扩展与邮箱验证 | `identity` + `shared` | `users` 增 `nickname`/`college`/`class_name`/`email_verified`；新增 `PATCH /api/v1/auth/me/profile` 与邮箱验证码发送/确认接口（Redis HMAC + Lua） | `c451483b0660` | [F10-profile-and-email-verify.md](../test/F10-profile-and-email-verify.md) |
| **F11** | 公开展示名供给面与个人主页 | `identity` + `qa` / `reputation` / `discovery` | `identity/application/ports.py` + `deps.py` 暴露 `UserSummaryReaderDep`/`PublicUserProfileReaderDep`；问答/评论/榜单/通知增量回填展示名；新增公开 `GET /api/v1/users/{user_id}/profile`（最小披露） | 无（复用 F10） | [F11-display-name-and-profile.md](../test/F11-display-name-and-profile.md) |
| **F12** | 编辑回答（US-A02） | `qa` | `Answer.edit_body()`（限作者本人且问题未关闭）；仓储分离正文更新与采纳条件更新；新增 `PATCH /api/v1/answers/{id}`；含 Hardening 关贴并发锁序收口 | 无 | [F12-edit-answer.md](../test/F12-edit-answer.md) |
| **F13** | 软删除与全链路过滤 | `qa` | `questions` / `answers` 增 `deleted_at`；强制“已采纳回答/问题不可删”409；新增 `DELETE /questions/{id}` 与 `DELETE /answers/{id}`（作者重复删幂等 204、删题退还开放悬赏）；全链路查询与 F06 六路统计全量剔除 | `c90363e3c1fb` | [F13-soft-delete.md](../test/F13-soft-delete.md) |
| **F14** | 评论二级回复 | `qa` + `discovery` | `comments` 增可空自引用 `parent_id`（`fk_comments_parent_id` `RESTRICT` + `ix_comments_parent_id` + `ck_comments_no_self_parent`）；严格两级树（跨宿主/三级 422、父不存在 404）；详情与编辑回答平铺有序返回 `parent_id`；`discovery` 新增 `comment_replied` / `comment` 通知类型并实现同人去重 | `609aeba713d3` | [F14-comment-replies.md](../test/F14-comment-replies.md) |
| **F15** | RBAC 扩展与教师认证回答 | `identity` + `qa` + `discovery` | `Role` 扩展 `ta`/`admin`（注册仍禁提权 422，DB 实时鉴权，角色变更保留学工号与唯一 `user_roles`）；新增 `GET /api/v1/admin/users`、`PATCH /api/v1/admin/users/{user_id}/role`（禁改本人 409/404）与 `scripts/seed_admin.py`；`_ROLE_PRIORITY` 定死 4 角色；`Answer` 增 `is_teacher_verified`/`verified_by`/`verified_at` 与 `AnswerResponse` 单源同步（详情零 N+1）；新增 `POST`/`DELETE /api/v1/answers/{answer_id}/verify`（`teacher`/`ta`/`admin` 幂等 200/204，单根无环锁序）与 `NotificationType.ANSWER_VERIFIED` 首次通知 | `0c58c26e2c45` | [F15-rbac-and-verify.md](../test/F15-rbac-and-verify.md) |
| **F16** | 重建 `course` 上下文与选课 | `course` | 四层重构与零跨上下文外键（`courses`/`enrollments`）；`CourseCode` 单源大写归一、`CourseName`/`Semester` 单行清洗；`GET/POST /api/v1/courses`、`POST /api/v1/courses/{course_id}/enroll`、`GET /api/v1/courses/{course_id}/students`（全角色权限矩阵 + F11 展示名回填 + 最小披露）；暴露窄只读已发布语言 `CourseAccessReaderDep` 供 F17 消费 | `965519fef7b7` | [F16-course-context.md](../test/F16-course-context.md) |
| **F17** | 问题关联课程与课程筛选/榜单 | `qa`（消费 `course`） | `questions` 增可空 `course_id`（零跨上下文外键）；`AskQuestionUseCase`/`EditQuestionUseCase` 应用层单源准入（选课学生/跨课教职/缺课 404/未选 403/解绑 `null`）；`GET /questions?course_id=...` 组合筛选与批量 `IN` 回填 `course_name`；`GET /api/v1/courses/{course_id}/leaderboard` 只读聚合（`RANK()`、防多票膨胀、剔除软删、零耦合 `reputation_ledgers`） | `13a011cb2db6` | [F17-question-course.md](../test/F17-question-course.md) |
| **F18** | 内容举报与管理员后台 | `qa` | 新增 `reports` 表（目标限 `question`/`answer`、部分唯一索引防并发重复 `pending` 409）；`POST /api/v1/reports`、`GET /api/v1/admin/reports`、`POST /api/v1/admin/reports/{report_id}/resolve`（3×2 处置矩阵策略注册 + 条件 `UPDATE` + `close_question`/`soft_delete` 同事务退还悬赏） | `78debaff54c7` | [F18-reports-admin.md](../test/F18-reports-admin.md) |

> 当前基线契约规模：**41 paths / 48 operations**（[openapi.json](../../openapi.json)），CI 单测 **479 passed**（总覆盖率 **84.44%**，domain **94%**）；F18 定向集成与并发连续 2 轮 **4 passed × 2**（25.92s / 25.90s），真实 Uvicorn 冒烟 **40 HTTP 请求全绿**；阶段 C（`v1.2.0`）全量真库集成回归 **238 passed**（441.11s，F01–F18 合计 **717 passed**）。

---

### 2. 后续规划路线图（F19–F20，顺接 F21）

> 阶段 A（F08–F11）、阶段 B（F12–F15，`v1.1.0`）与阶段 C（F16–F18，`v1.2.0`）均已归入 §5.1 基线表。

#### 阶段 D：阶段 4 容器化上线与可观测性（F19–F20；顺接 F21）

| 编号 | 名称 | 核心工程内容 | 迁移 |
|:---|:---|:---|:---|
| **F19** | 可观测性、生命周期与死信防噪 | `app/platform/http/` 挂载 Prometheus `/metrics`（RED 指标 + 连接池状态）；`loguru` 统一结构化 JSON 日志；[app/main.py](../../app/main.py) 接入 `lifespan` 优雅释放引擎/Redis；Celery 补死信记录防陈旧消息刷屏 | 否 |
| **F20** | 容器化编排、Grafana 与 CD 流水线 | 后端/前端多阶段 `Dockerfile` 与 `deploy/nginx.conf`；生产 `docker-compose`（`api` + `worker` + `frontend` + `db` + `redis` + `prometheus` + `grafana`，内部直连避开宿主保留端口）；Grafana Dashboard、告警规则、CD 部署与《运维手册 v1.0》 | 否 |
| *顺接 **F21*** | *`@` 提醒（已预留）* | *复用 `NotificationModel.payload` 与 `NotificationType.MENTION`，在回答/评论时解析 `@学号/工号` 写站内通知* | *否* |

---

## 六、标准台账模板（新建 `docs/test/Fxx-<slug>.md` 时复制）

```markdown
# Fxx <特性名称> · 开发与测试台账

> 日期：YYYY-MM-DD · 上下文：<context> · 依赖：<前置 Fxx 或无>
> 裁定：D1=... · D2=...
> 分支/工作区：<branch>

## 一、交付范围

（列出新增/调整端点、请求参数、状态码与语义口径）

明确不做：<列出明确边界>

## 二、六步法改动清单

| 步骤 | 文件 | 改动 |
|:--|:--|:--|
| 1 domain | ... | ... |
| 2 application | ... | ... |
| 3 infrastructure | ... | ... |
| 4 interfaces | ... | ... |
| 5 tests | ... | ... |
| 6 收口 | ... | ... |

### 关键设计
- 并发与一致性：...
- 边界与错误处理：...

## 三、门禁实测（YYYY-MM-DD）

| 门禁 | 命令 | 结果 |
|:--|:--|:--|
| Lint | `ruff check .` | ... |
| 类型 | `mypy app` | ... |
| 单元 + 覆盖率 | `pytest -m "not integration" --cov=app --cov-fail-under=70` | ... |
| 核心聚合 | `python -m coverage report --include="*/domain/*" --fail-under=90` | ... |
| 契约检查 | `python scripts/export_openapi.py --check` | ... |
| 集成测试 | `pytest -m integration` | ... |

## 四、测试覆盖
（按文件列出新增/修改测试条数及覆盖点）

## 五、DoD 勾选

- [ ] 六步法落地，仅触及本 Fxx 范围，`test_architecture.py` 全绿
- [ ] 迁移已人工审核并完成 down→up 往返验证（若无需迁移则写“无需迁移”）
- [ ] 单元 + 集成 + 并发测试写入 `tests/` 并实测通过
- [ ] `openapi.json` 与 `tests/test_contract.py` 已同步且过 `--check`
- [ ] 本台账与 `docs/PROGRESS.md`、`docs/api/api-contract-notes.md` 已登记
- [ ] 本地门禁与远端 CI 全绿
```
