# F12 编辑回答（US-A02）· 开发与测试台账

> 日期：2026-11-18 · 上下文：`qa` · 依赖：F11（`AnswerResponse.author_name` / `UserSummaryReaderDep`）
> 裁定：D1 权限/错误码（403/404/409/422）· D2 已采纳回答在问题未关闭时仍可编辑 · D3 `update_body` 与采纳翻转 `update` 分离 · D4 问题行锁 + 条件 `UPDATE` 并发兜底 · D5 PATCH 返回完整 `AnswerResponse`（真实 votes、author_name、有序 comments）
> 分支/工作区：`feat/f12-edit-answer`

## 一、交付范围

| 交付项 | 语义 |
|:--|:--|
| `PATCH /api/v1/answers/{answer_id}` | 需登录（401）；**仅回答者本人**可编辑（非作者含提问者 **403** `"仅回答者可编辑回答"`）；回答不存在 404；所属问题已关闭 409；正文非法 422 |
| 请求体 | `{"body": "1~5000 字"}`；`extra=forbid` + `str_strip_whitespace=True` + `reject_unsafe_text`；纯空白/超长/控制字符 → 422 |
| 成功响应 | **200 + `AnswerResponse`**：最新正文、真实净票数 `votes`、`author_name`、`is_accepted` 保留、完整有序 `comments[]`（含评论者 `author_name`） |
| 领域行为 | `Answer.edit_body()` 仅替换正文，保留 `is_accepted`/`votes_count`/`author_id`/`question_id`；新增 `NotAnswerAuthorError` |
| 仓储 | 新增独立 `AnswerRepository.update_body(answer)`；不触碰 `is_accepted`，条件 `UPDATE` 兜底问题未关闭，`rowcount=0` 转译 404/409 |

明确不做：新建 Alembic 迁移（`answers` 表无 `updated_at`，零迁移）；编辑他人回答（管理员/提问者也不越权）；通过编辑修改 `question_id`/`author_id`/`is_accepted`；前端 UI 与 API 客户端改动。

## 二、六步法改动清单

| 步骤 | 文件 | 改动 |
|:--|:--|:--|
| 1 domain | `app/contexts/qa/domain/answer.py`、`errors.py`、`repository.py` | `Answer.edit_body()`；`NotAnswerAuthorError(QADomainError)`；`AnswerRepository.update_body()` 端口（与采纳 `update()` 职责分离） |
| 2 application | `app/contexts/qa/application/commands.py`、`edit_answer_use_case.py` | `EditAnswerCommand`；`EditAnswerUseCase`：404 → 403 → 问题行锁 `for_update=True` → `ensure_open("编辑回答")` → `edit_body` → `update_body` |
| 3 infrastructure | `app/contexts/qa/infrastructure/answer_repository.py` | `update_body` 条件 `UPDATE`：`EXISTS(questions.status <> 'closed').correlate(AnswerModel)`；仅写 `body`，不触碰 `is_accepted`；`rowcount=0` 复查转译 `AnswerNotFoundError`/`QuestionClosedError` |
| 4 interfaces | `app/contexts/qa/interfaces/api/error_mapping.py`、`schemas.py`、`answers.py` | `NotAnswerAuthorError → 403`；`EditAnswerRequest`；`PATCH /{answer_id}` 返回 `AnswerResponse`（读取评论并批量回填评论者展示名） |
| 5 tests | 领域/用例/fake/仓储/API 测试 | 新增单测 +15、集成 +5；同步 5 个 `FakeAnswerRepository` 的 `update_body`；契约计数 `31 paths / 34 operations` |
| 6 收口 | `openapi.json`、`tests/test_contract.py`、本台账、`docs/api/api-contract-notes.md`、`docs/PROGRESS.md`、`README.md` | 契约导出与防漂移、文档与门禁数字登记 |

### 关键设计

- **仓储职责分离**：既有 `update()` 硬编码采纳翻转（`WHERE is_accepted=false`），编辑复用会误采纳或误报 409；`update_body()` 独立实现，只更新正文。
- **并发一致性**：编辑先对所属问题 `SELECT ... FOR UPDATE`，与关闭/采纳的锁顺序一致（均先锁问题行），避免死锁；条件 `UPDATE` 在库级再兜底一次“问题未关闭”，关闭先提交时返回 409 且不落正文。
- **响应完整性**：PATCH 返回真实 `votes`（`get_by_id` 已回填净票数）与完整 `comments[]`，避免前端用 PATCH 响应刷新本地状态时丢失既有评论；评论作者展示名经 F11 `UserSummaryReader` 单次批量回填。
- **SQL 成本口径**：`get_by_id` 包含回答查询 + 净票数查询；有评论时再 1 条评论查询 + 1 条摘要查询；`author_name` 本身不额外查用户。

### 已知边界与后续项（不阻塞 F12）

1. **同会话读旧缓存（潜伏）**：`update_body()` 使用 `synchronize_session=False`，而 `SqlAlchemyAnswerRepository.get_by_id()` 当前未带 `populate_existing=True`；每请求独立 `AsyncSession` 下不触发，若后续出现同一会话内“先 `update_body` 再 `get_by_id`”的场景，单开 hardening 提交补齐 `populate_existing=True` 与回归测试。
2. **并发瞬时快照**：PATCH 响应中的 `votes`/`is_accepted` 为加锁前读取快照，同瞬间并发投票/采纳时响应可能短暂滞后，数据库写入本身不受影响且不会覆盖 `is_accepted`（已写入 `api-contract-notes.md`）。
3. **存量写路径关闭竞态（非 F12 引入）**：`VoteOnUseCase`、`PostAnswerUseCase`、`CreateCommentUseCase` 校验 `question.ensure_open()` 时未对问题行加 `for_update=True`，极高并发关贴窗口存在既有竞态，留待独立 hardening 收口。

## 三、门禁实测（2026-11-18）

| 门禁 | 命令 | 结果 |
|:--|:--|:--|
| Lint | `ruff check .` | `All checks passed!` |
| 类型 | `mypy app` | `Success: no issues found in 144 source files` |
| 契约防漂移 | `python scripts/export_openapi.py --check` | `openapi.json 与当前代码一致`（**31 paths / 34 operations**） |
| 架构 + 契约测试 | `pytest tests/test_architecture.py tests/test_contract.py -q` | **15 passed** |
| 单元 + 总覆盖率 | `pytest -m "not integration" --cov=app --cov-report=term-missing --cov-fail-under=70 -q` | **345 passed**, 199 deselected；TOTAL **83.42%** |
| 核心聚合覆盖率 | `python -m coverage report --include="*/domain/*" --fail-under=90` | **94%** |
| 全量集成 | `pytest -m integration -q` | **199 passed**, 345 deselected（285.01s） |
| 迁移状态 | `alembic current` | `c451483b0660 (head)`；本特性无新增迁移 |

> 环境说明：本机 5432 落入 Windows 保留端口段，集成实测使用 `DB_PORT=15432` 临时宿主端口（通过 `DATABASE_URL` 覆盖指向该端口）；代码与仓库配置未改动。

## 四、测试覆盖

| 文件 | 条数 | 覆盖点 |
|:--|:--|:--|
| `tests/contexts/qa/domain/test_answer.py` | 新建 | `Answer.edit_body` 正文校验与 `is_accepted`/`votes_count` 保留 |
| `tests/contexts/qa/application/test_edit_answer_use_case.py` | 新建 | 正常编辑、404（回答/问题）、403 非作者、409 已关闭、422 空/空白/超长/NUL；验证问题 `for_update=True` 与不调用采纳 `update` |
| `tests/contexts/qa/application/*`（5 个 fake） | 同步 | `FakeAnswerRepository` 补 `update_body`（含 `test_notification_hooks.py`） |
| `tests/contexts/qa/infrastructure/test_edit_answer_repository.py` | 2（新建集成） | 正文更新且不触碰 `is_accepted`；关闭问题/缺失回答的库级守卫 |
| `tests/contexts/qa/interfaces/test_edit_answer_api.py` | 3（新建集成） | 完整响应（votes/author_name/comments/已采纳编辑）；权限与错误码矩阵；`asyncio.gather` 双线性化顺序并发实证 |
| `tests/test_contract.py` | 同步 | `_FAMILIES["qa"]` 增 `/api/v1/answers/{answer_id}`；计数 `31 paths / 34 operations` |

## 五、DoD 勾选

- [x] 六步法落地，仅触及 F12 范围，`test_architecture.py` 全绿
- [x] 无需迁移（`answers` 表无 `updated_at`）
- [x] 单元 + 集成 + 并发竞态测试写入 `tests/` 并实测通过
- [x] `openapi.json` 与 `tests/test_contract.py` 已同步且过 `--check`
- [x] 本台账与 `docs/PROGRESS.md`、`docs/api/api-contract-notes.md`、`README.md` 已登记
- [x] 本地门禁全绿（ruff / mypy / 单元+覆盖率 / 全量集成）
