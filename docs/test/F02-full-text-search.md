# F02 全文搜索（ILIKE 基础版）· 开发与测试台账

> 日期：2026-11-12 · 上下文：qa · 依赖：F01（`QuestionFilter` / `_apply_filters` 扩展点）
> 选型裁定：**方法 v2（ILIKE）**，不上 tsvector——课程 2.3.4 明文允许 LIKE 基础版；无中文分词扩展时 tsvector 对中文站点是负优化
> 分支/工作区：`feat/question-filter` 工作树（叠加 F01 未提交改动），未 commit

## 一、交付范围

`GET /api/v1/questions` 新增可选参数 `q`，空值/纯空白与不传等价：

| 项 | 口径 |
|:--|:--|
| 匹配范围 | 标题 + 正文，`ILIKE '%q%'`，大小写不敏感；标签/答案/评论不参与 |
| 空值 | strip 后为空 → `None`（不进 SQL） |
| 长度 | 至多 100 字，超限 `DomainValidationError` → 422（D5） |
| 字符 | 制表符/换行/回车 → 422（D7）；其余控制字符与 lone surrogate 复用 `reject_unsafe_text` → 422 |
| 通配符 | `%`、`_`、`\` 经 `escape_like` 字面转义，与 SQL `escape="\\"` 成对 |
| 组合 | 与 `tag`/`status`/`created_from`/`created_to`/`sort`/分页任意组合，`total` 同口径 |
| 状态 | `q` 不额外限制状态；关闭问题是否出现由 `status` 筛选决定 |

明确不做：PostgreSQL 全文索引/中文分词、搜索答案与评论、搜索历史/热词、前端搜索框、标签名匹配。

## 二、六步法改动清单

| 步骤 | 文件 | 改动 |
|:--|:--|:--|
| 1 domain | `app/contexts/qa/domain/repository.py` | `QuestionFilter.q`：strip 回写、空串归一 None、`\t\n\r` 拒绝、`reject_unsafe_text`、`_MAX_QUERY_LENGTH=100` |
| 2 application | 无改动 | `ListQuestionsQuery.filters` 原样透传，已实证 |
| 3 infrastructure | `app/contexts/qa/infrastructure/sql_expressions.py`、`question_repository.py` | 新增 `escape_like()`（顺序 `\` → `%` → `_`）；`_apply_filters` 在时间条件后、tag EXISTS 前加 `q` 分支：`or_(title.ilike, body.ilike)`，单条件 OR 天然去重 |
| 4 interfaces | `app/contexts/qa/interfaces/api/questions.py` | 列表路由新增 `q` Query 参数并透传，零新增 try/except 与校验分支 |
| 5 tests | 见第四节 | domain 13、infra 纯函数 8、仓储集成 4、API 集成 5 |
| 6 收口 | 契约 + 文档 | `openapi.json` 重导出 `--check` 一致；契约说明、Gherkin、本台账、PROGRESS 同步 |

### 关键设计

- **无迁移、无索引**：课程数据量（百级）下 ILIKE 顺序扫描无感知；不新增 `pg_trgm` 等扩展，保持演示环境零依赖。
- **单谓词源**：`q` 与 F01 条件同走 `_apply_filters`，COUNT 与分页 SELECT 共用，杜绝 `total` 不自洽。
- **转义单源**：`escape_like` 是唯一转义实现；SQL `escape` 参数与之成对，避免双实现漂移。

## 三、门禁实测（2026-11-12）

| 门禁 | 命令 | 结果 |
|:--|:--|:--|
| Lint | `ruff check .` | All checks passed（0） |
| 类型 | `mypy app` | 0 errors（100 文件） |
| 单元（CI 口径） | `pytest -m "not integration" --cov=app --cov-fail-under=70` | **239 passed**（138 deselected），TOTAL **83.26%**（2115 语句 / 354 未覆盖） |
| 核心聚合 | `coverage report --include="*/domain/*" --fail-under=90` | **95%**（483 语句 / 22 未覆盖） |
| 契约导出 | `scripts/export_openapi.py` + `--check` | 一致（**17 paths / 19 operations** 未变，仅新增 query 参数） |
| 定向集成（F02 两文件） | `pytest -q tests/contexts/qa/infrastructure/test_question_repository.py tests/contexts/qa/interfaces/test_question_api.py` | **46 passed**（45.22s），含 F02 新增 9 条集成用例全绿 |
| 全量（含 integration） | `pytest -q` | **377 passed**（186.43s = 239 单测 + 138 集成）。首轮曾出现 1 条 **F02 范围外**的瞬时抖动：`identity/test_login_lockout_api.py::test_success_clears_counter_so_filter_restarts_fresh` 返回 503（预期 401），定向重跑 5 passed、全量复跑 377 全绿，判定为环境瞬时波动而非缺陷，仅登记不处理 |

## 四、测试覆盖

### 4.1 新增用例

| 文件 | 条数 | 覆盖点 |
|:--|:--|:--|
| `tests/contexts/qa/domain/test_question_filter.py` | 13 | 默认 None、strip 回写、空串/纯空白归一、NUL、lone surrogate、`\t\n\r`、100 字边界、101 字 422、与 F01 条件共存 |
| `tests/contexts/qa/infrastructure/test_sql_expressions.py` | 8 | 普通文本、空串、`%`、`_`、`\`、混合串、两组转义顺序守卫 |
| `tests/contexts/qa/infrastructure/test_question_repository.py` | 4 | 标题/正文命中、双命中单行、无关不命中；大小写不敏感；`%`/`_`/`\` 字面匹配；`q + status` 组合 total 对账 |
| `tests/contexts/qa/interfaces/test_question_api.py` | 5 | 标题/正文命中与无命中空列表；大小写 + 空白 q 等价不传；`%` 字面匹配端到端；`q + tag` 组合；101 字与制表符 422 且不回显 |

### 4.2 测试矩阵要点

- **命中面**：标题命中、正文命中、标题+正文双命中只返回一行（OR 非 JOIN）。
- **字面通配符**：`100%` 不匹配 `100x`；`a_b` 不匹配 `axb`；`path\to` 不匹配 `pathXto`。
- **组合**：`q + tag=React` 只返回同时满足者，`total == len(items)`。
- **边界**：`q=""` / `"   "` → 与不传 `total` 一致；`q="a"*101` → 422；`q` 含 `\t` → 422。
- **不可经 API 构造**：lone surrogate 无法通过 httpx 发出，保留在 domain 单测。

### 4.3 本轮缺陷

无产品缺陷。纯函数用例首次运行即全绿；未出现测试自身假失败。

## 五、DoD 勾选

- [x] 六步法落地，仅触及本 Fxx 点名对象
- [x] 无表结构变更，无需迁移
- [x] 单元 + 集成测试已写入 `tests/`
- [x] `openapi.json` 重导出且 `--check` 一致
- [x] 本台账登记
- [x] `docs/PROGRESS.md` 变更记录登记
- [x] 门禁：ruff 0 / mypy 0 / coverage 83.26%（≥70%）/ domain 95%（≥90%）
- [x] 全量 pytest（含 integration）：**377 passed**（186.43s，2026-11-12 引擎恢复后补跑）
- [x] 未执行任何 commit/push

## 六、文档同步

- `docs/api/api-contract-notes.md`：分页契约补 `q` 搜索口径与 422 形态
- `docs/sprint/acceptance-criteria.feature`：新增功能域 12（问题搜索，6 场景）
- `docs/PROGRESS.md`：变更记录新增本 Fxx 行

## 七、遗留

- 中文分词/全文索引进阶（tsvector + zhparser/pg_jieba）不在本项范围；如数据量增长再单独立项。
- 按课程筛选由 F17（依赖 F16）收口；相关问题推荐由 F03 收口。
