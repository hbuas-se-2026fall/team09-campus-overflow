# F13 软删除与全链路过滤 · 开发与测试台账

> 日期：2026-11-19 · 上下文：`qa` · 依赖：F01–F03（筛选/搜索/相关）、F06（徽章统计）、F07（悬赏退款）、F12（回答编辑）
> 裁定：D1 删除权限与幂等矩阵（403 先于 409；作者重复删 204、非作者 404；父问题已删统一 404）· D2 选 B（已采纳回答及含采纳答案的问题均不可删 → 409，单异常 `AcceptedAnswerCannotDeleteError`）· D3 删含开放悬赏问题同事务全额退款，重复删不二次退；已关闭问题本体及关闭问题下回答允许作者软删除（内容回收例外）· D4 `AnswerRepository.get_by_id`/`list_by_question` JOIN 过滤父问题 `deleted_at`，5 条答入口写用例统一“锁父问题后重读 Answer”，`parent is None` 一律 404 · D5 徽章统计全量剔除（含 6 路活跃日 UNION，历史连续活跃天数可下降）· D6 三处条件 `UPDATE` 加 `deleted_at IS NULL` 并精准转译 404/409 · D7 `soft_delete` 独立成端口返回 `bool` 门控退款，`QuestionRepository.get_by_id` 补 `populate_existing=True`，`EditQuestionUseCase` 补 `for_update=True` · D8 `_apply_filters` 在 `filters is None` 早退前强制过滤，`list_related` 补过滤 · D9 契约 `31 paths / 36 operations`，迁移 `c90363e3c1fb` 仅加两列不动既有索引 · D10 Non-Goals
> 分支/工作区：`feat/f13-soft-delete`（未 commit，待 PR 合入 `main`）

## 一、交付范围

| 交付项 | 语义 |
|:--|:--|
| `DELETE /api/v1/questions/{question_id}` | 需登录（401）；仅提问者可删（活跃态非作者 **403**，鉴权先于 409）；已有采纳答案 **409**；成功 **204**（同步退还开放悬赏）；作者重复删幂等 **204**（不二次退款）；非作者对已删/不存在 **404**；已关闭问题允许删除 |
| `DELETE /api/v1/answers/{answer_id}` | 需登录（401）；仅回答者可删（父问题与回答均活跃时非作者 **403**，鉴权先于 409）；已采纳回答 **409**；成功 **204**；父问题活跃时作者重复删幂等 **204**；非作者对已删回答、或父问题已删时任意用户统一 **404**；已关闭问题下允许删回答 |
| 全链路查询与统计过滤 | 列表（含无参 `filters=None` / 搜索 / 筛选 / `sort=votes` / `total`）、详情、相关推荐、悬赏查询、全部写入口及 F06 徽章统计（回答数/采纳率/6 路活跃日）全量排除已删问题、已删回答及所属问题已删的回答/评论/投票 |
| 迁移 | `alembic/versions/c90363e3c1fb_add_soft_delete_columns_f13.py`（仅新增 `questions.deleted_at` 与 `answers.deleted_at` 可空 `TIMESTAMPTZ` 列） |

明确不做（D10 Non-Goals）：回滚声誉流水/排行榜（守 `reputation` 不可变流水不变式与 A5 零耦合）；清理或过滤历史通知；回收孤儿标签；恢复/回收站；物理删除；管理员删帖（留待 F18）；前端改动；新增部分索引（保留 `uq_answers_one_accepted_per_question` 与 F09 两枚 `pg_trgm` 索引不动）。

## 二、六步法改动清单

| 步骤 | 文件 | 改动 |
|:--|:--|:--|
| 1 domain | `app/contexts/qa/domain/errors.py`、`question.py`、`answer.py`、`repository.py` | 新增 `AcceptedAnswerCannotDeleteError`；`Question`/`Answer` 增 `deleted_at`、`is_deleted`、`soft_delete()`；仓储端口增 `include_deleted` 与独立 `soft_delete()` |
| 2 application | `app/contexts/qa/application/commands.py`、`bounty_service.py`、`delete_question_use_case.py`（新建）、`delete_answer_use_case.py`（新建）、`vote_use_case.py`、`comment_use_case.py`、`accept_use_case.py`、`edit_answer_use_case.py`、`edit_question_use_case.py` | 新增删题/删答命令与用例；`BountyService` 保留 `refund_on_close` 并增 `refund_on_delete`；`VoteOn`/`CreateComment` 消除 `parent is None` 静默跳过；4 条答入口统一锁父问题后重读 `Answer`；`EditQuestionUseCase` 补 `for_update=True` |
| 3 infrastructure | `app/contexts/qa/infrastructure/models.py`、`question_repository.py`、`answer_repository.py`、`user_activity_repository.py`、`alembic/versions/c90363e3c1fb_add_soft_delete_columns_f13.py`（新建） | 模型增 `deleted_at` 列与迁移；`_apply_filters` 无条件置顶过滤；`list_related` 补过滤；`AnswerRepository` JOIN 过滤父问题 `deleted_at` 并移除 `update()` `session.get` 死分支；三处 `update`/`update_body` 的 `rowcount=0` 精准区分 404/409；`UserActivityRepository` 6 路 UNION 全量剔除 |
| 4 interfaces | `app/contexts/qa/interfaces/api/error_mapping.py`、`questions.py`、`answers.py` | 注册 `AcceptedAnswerCannotDeleteError → 409`；新增 `DELETE /api/v1/questions/{question_id}` 与 `DELETE /api/v1/answers/{answer_id}` |
| 5 tests | 领域/用例/fake/仓储/API 并发/契约测试 | 同步 8 个 `FakeQuestionRepository` 与 6 个 `FakeAnswerRepository`；扩展领域与用例单测；新建 `test_delete_use_cases.py`、`test_soft_delete_repository.py`、`test_soft_delete_api.py`（含 `asyncio.gather` 并发实证）；更新 `tests/test_contract.py` 至 `31 paths / 36 operations` |
| 6 收口 | `openapi.json`、本台账、`docs/PROGRESS.md`、`docs/api/api-contract-notes.md`、`README.md`、`docs/plan/f-engineering-standard.md` | 契约重导出 `--check` 一致与文档台账同步 |

### 关键设计
- **单根无环锁序**：`Question` 行作为全写路径（`close`/`edit_question`/`post_answer`/`vote`/`comment`/`accept`/`edit_answer`/`create_bounty`/`delete_question`/`delete_answer`）的统一锁根；涉及悬赏资金流时保持 `Question → PointsAccount` 同序无环；所有答入口写用例遵循“先无锁读 Answer → 锁父 Question → 重读 Answer”闭环并发软删除窗口。
- **库级条件兜底与精准转译**：`QuestionRepository.soft_delete`、`AnswerRepository.soft_delete`、`QuestionRepository.update`、`AnswerRepository.update`、`AnswerRepository.update_body` 全部配备条件 `WHERE ... deleted_at IS NULL`，并在 `rowcount == 0` 时联查最新行，严格将“已删”转译为 404、“已关/已采纳”转译为 409。

### 回归与冒烟检出记录（问题与缺陷）
1. **代码设计期检出并已在本特性内根治的 3 类存量/潜在缺陷**：
   - `VoteOnUseCase` / `CreateCommentUseCase` 原先对 `parent is None` 静默跳过 `ensure_open()`，软删除后会导致已删问题下的答票/答评绕过校验并继续写库与发事件 → 已改为抛出 `QuestionNotFoundError`（404）并锁后重读 `Answer`；
   - `SqlAlchemyAnswerRepository.update()` 原先存在 `session.get(...)` 后 `if model is None: return` 的静默放行死分支 → 已删除并改为条件 `UPDATE` + `rowcount=0` 联查精确转译 404/409；
   - `SqlAlchemyAnswerRepository.get_by_id()` 若不 JOIN 过滤 `QuestionModel.deleted_at IS NULL`，父问题已删时非作者调用 `PATCH /answers/{id}` 会先命中 403 泄露存在性 → 已统一 JOIN 过滤父问题 `deleted_at`。
2. **本轮静态门禁检出并已修复**：新增 5 个测试文件首次 `ruff check` 检出 8 处 `E501`（行长 > 100）及迁移脚本 1 处 `I001`（import 排序），均已修复至 `ruff` 0 违规。
3. **本轮定向回归与真实冒烟测试结果**：**未检出任何产品代码 bug**（全部 366 单测、22 条定向集成回归、8 组真实 Uvicorn HTTP 冒烟全绿；冒烟脚本首次运行遇到的 `ReadTimeout` 经排查为测试脚本未排空 Windows 4KB `subprocess.PIPE` 导致 Uvicorn 访问日志阻塞，改为写日志文件后 46 条请求全绿、零 500、零异常栈）。

## 三、门禁、回归与冒烟实测（2026-11-19）

| 检查项 | 命令 | 结果 |
|:--|:--|:--|
| Lint | `.venv\Scripts\ruff.exe check .` | `All checks passed!`（0 违规） |
| 严格类型检查 | `.venv\Scripts\mypy.exe app` | `Success: no issues found in 146 source files` |
| 契约导出与防漂移 | `.venv\Scripts\python.exe scripts/export_openapi.py --check` | 一致（**31 paths / 36 operations**） |
| 架构 + 契约测试 | `.venv\Scripts\pytest.exe tests/test_architecture.py tests/test_contract.py -q` | **15 passed** |
| CI 单元回归 + 覆盖率 | `.venv\Scripts\pytest.exe -m "not integration" --cov=app --cov-report=term-missing --cov-fail-under=70 -q` | **366 passed**, 213 deselected；TOTAL **82.76%** |
| 核心聚合覆盖率 | `.venv\Scripts\python.exe -m coverage report --include="*/domain/*" --fail-under=90` | **94%**（`question.py`/`answer.py`/`errors.py` 均 100%） |
| 迁移往返与零漂移 | `alembic upgrade head` → `downgrade -1` → `upgrade head` → `current` → `check`（`DB_PORT=15432`） | `c90363e3c1fb (head)`，`No new upgrade operations detected.` |
| 定向集成回归（F13 + 受影响 F06/F07/F12） | `.venv\Scripts\pytest.exe tests/contexts/qa/infrastructure/test_soft_delete_repository.py tests/contexts/qa/interfaces/test_soft_delete_api.py tests/contexts/qa/infrastructure/test_edit_answer_repository.py tests/contexts/qa/interfaces/test_edit_answer_api.py tests/contexts/qa/interfaces/test_badges_api.py tests/contexts/qa/interfaces/test_bounty_api.py -q` | **22 passed**（55.89s） |
| 真实服务冒烟测试 | 真实 `uvicorn app.main:app`（`127.0.0.1:18123`，连 PG `15432` + Redis `16379`）8 组端到端闭环（46 条 HTTP 请求） | **8/8 PASS**，服务端日志零 500 / 零异常栈 |
| 全量集成套件（`pytest -m integration`） | 按用户指令「先不进行全量测试，只进行回归测试和冒烟测试」 | **未验证**（待合入前或按需执行） |

### 测试数据知识来源（遵循真实知识测试数据规范）
- PostgreSQL B-Tree Indexes Implementation（MVCC、去重、HOT、Bottom-Up Index Deletion）：`https://www.postgresql.org/docs/current/btree-implementation.html`
- PostgreSQL Routine Vacuuming（Visibility Map、`all-visible`/`all-frozen`、死元组回收）：`https://www.postgresql.org/docs/current/routine-vacuuming.html`

## 四、测试覆盖

| 文件 | 改动 | 覆盖点 |
|:--|:--|:--|
| `tests/contexts/qa/domain/test_question.py` | +3 单测 | 开放/已关闭问题软删除、重复删幂等保留时间戳、已采纳 409 |
| `tests/contexts/qa/domain/test_answer.py` | +2 单测 | 未采纳回答软删除与幂等、已采纳回答 409 |
| `tests/contexts/qa/application/test_delete_use_cases.py` | +10 单测（新建） | `DeleteQuestionUseCase` / `DeleteAnswerUseCase` 完整 D1–D4/D7 矩阵（403 先于 409、重复删不二次退悬赏、父问题已删对所有人 404、锁后重读捕获并发采纳） |
| `tests/contexts/qa/application/*`（4 文件） | +5 单测 + 同步 8/6 个 fake | `VoteOn`/`CreateComment` `parent is None` 404；4 条答入口锁后重读 Answer 404；`EditQuestion` `for_update=True` |
| `tests/contexts/qa/infrastructure/test_soft_delete_repository.py` | +4 集成（新建） | 题/答 `soft_delete` 库级守卫、同会话 `populate_existing` 刷新、无参/有参列表与相关推荐过滤、三处 `update`/`update_body` 转 404、`UserActivityRepository` 6 路全量剔除 |
| `tests/contexts/qa/interfaces/test_soft_delete_api.py` | +4 集成（新建） | 全状态码矩阵、全链路过滤与徽章/悬赏退款实证、`asyncio.gather` 多路并发删+删×采纳+删×投票/评论双线性化实证 |
| `tests/test_contract.py` | 同步 | 契约计数 `31 paths / 36 operations` |

## 五、DoD 勾选

- [x] 六步法落地，仅触及 F13 范围，`test_architecture.py` 全绿
- [x] 迁移 `c90363e3c1fb` 已人工审核并完成 `down → up` 往返与 `alembic check` 零漂移验证
- [x] 单元 + 定向集成 + 并发测试写入 `tests/` 并实测通过；端到端真实冒烟测试全绿
- [x] `openapi.json` 与 `tests/test_contract.py` 已同步且过 `--check`
- [x] 本台账、`docs/PROGRESS.md`、`docs/api/api-contract-notes.md`、`README.md`、`docs/plan/f-engineering-standard.md` 已同步
- [ ] 全量集成测试（按用户要求本轮未跑）与经批准推送 `feat/f13-soft-delete` 提 PR 及 Actions 全绿
