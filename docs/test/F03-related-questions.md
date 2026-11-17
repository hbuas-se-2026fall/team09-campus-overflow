# F03 相关问题推荐 · 开发与测试台账

> 日期：2026-11-12 · 上下文：qa · 依赖：F01（`QuestionFilter` 扩展）、F02（`_rebuild_question` 共用路径）
> 裁定：D1=qa · D2=独立端点 · D3=不过滤关闭态
> 分支/工作区：`feat/question-filter` 工作树（叠加 F02 未提交改动），未 commit

## 一、交付范围

新增 `GET /api/v1/questions/{question_id}/related`（访客可用）：

| 项 | 口径 |
|:--|:--|
| 返回 | `QuestionListItem[]`，无分页无 `total`（读模型语义） |
| `limit` | 1~10，默认 5；越界 422（路由 `Query` 校验） |
| 排序 | 标签重合数降序 → 净票数降序 → `created_at` 降序 → `id` 降序（确定性全序） |
| 排除 | 自身恒不出现 |
| 空集 | 无标签问题返回 200 空数组；不存在问题 404（`"问题不存在"`，与详情同语义） |
| 状态 | 关闭问题仍可被推荐（D3，与 F01/F02 状态口径一致） |

明确不做：基于行为/协同过滤的推荐、前端推荐位、分页、软删除过滤（F13 落地后统一回改）。

## 二、六步法改动清单

| 步骤 | 文件 | 改动 |
|:--|:--|:--|
| 1 domain | `app/contexts/qa/domain/repository.py` | `QuestionRepository` +`list_related(question_id, limit)`；宽接口注记 4→5 方法 |
| 2 application | `app/contexts/qa/application/queries.py`、`list_related_questions_use_case.py` | +`ListRelatedQuestionsQuery`；新只读用例：先 `get_by_id` 判存在（None→路由 404），再委托仓储 |
| 3 infrastructure | `app/contexts/qa/infrastructure/question_repository.py` | +`list_related`：种子标签键集 → 空则短路；`question_tags` 自连接聚合重合数；净票复用 `_question_net_votes()`；排除自身 + 全序 + LIMIT；抽出 `_rebuild_question` 供三处共用（零行为变更） |
| 4 interfaces | `app/contexts/qa/interfaces/api/questions.py` | 详情路由后新增 related 路由，`limit` Query(ge=1, le=10, default=5)；404 文案与详情一致 |
| 5 tests | 见第四节 | application 2 条、仓储集成 7 条、API 集成 4 条；5 个 fake 同步补 `list_related` |
| 6 收口 | 契约 + 文档 | `openapi.json` 重导出（**18 paths / 20 ops**）`--check` 一致；契约说明、台账、PROGRESS 同步；`tests/test_contract.py` 计数 17/19→18/20 |

### 关键设计

- **单 SQL**：主查询一条聚合 SQL；结果行的标签经 `_tags_for` 一次批量装配（既有防 N+1 路径），全流程 3 条查询（存在性、种子标签、主查询+标签批装）。
- **确定性全序**：重合数、净票、时间、id 四级排序，跨调用稳定。
- **无新表/无索引/无迁移**：`question_tags` 与 `tags` 现有索引可支撑当前数据量。

## 三、门禁实测（2026-11-12）

| 门禁 | 命令 | 结果 |
|:--|:--|:--|
| Lint | `ruff check .` | All checks passed（0） |
| 类型 | `mypy app` | 0 errors（**101 文件**） |
| 单元（CI 口径） | `pytest -m "not integration" --cov=app --cov-fail-under=70` | **241 passed**（149 deselected），TOTAL **82.85%** |
| 核心聚合 | `coverage report --include="*/domain/*" --fail-under=90` | **95%**（485 语句 / 23 未覆盖） |
| 契约导出 | `scripts/export_openapi.py` + `--check` | 一致（**18 paths / 20 operations**） |
| 全量（含 integration） | `pytest -q` | **390 passed**（157.49s；241 单测 + 149 集成）。本机 5432/6379 落入 Windows Hyper-V 排除段（5403–5502 / 6293–6392），以临时容器映射 15432/6393 完成补跑 |

## 四、测试覆盖

### 4.1 新增用例

| 文件 | 条数 | 覆盖点 |
|:--|:--|:--|
| `tests/contexts/qa/application/test_question_query_use_cases.py` | 2 | 用例透传 `question_id/limit` 并返回候选；不存在返回 None 且不触发相关查询 |
| `tests/contexts/qa/infrastructure/test_question_repository.py` | 7 | 重合数降序；同重合按净票；时间/id 双 tiebreak；自身排除 + limit 截断；无标签空；关闭题可见；不存在问题空 |
| `tests/contexts/qa/interfaces/test_question_api.py` | 4 | 200 排序与自身排除；limit 0/11→422；不存在→404；无标签→200 `[]` |

### 4.2 测试矩阵要点

- **重合优先**：3 标签重合 > 2 标签重合 > 1 标签重合，且三者 created_at 递增（证明重合数压过时间）。
- **票数 tiebreak**：同重合下，有 1 赞的较旧问题压过更新的 0 赞问题。
- **全序 tiebreak**：同重合同票，较新在前；同刻按 id 降序。
- **自身排除**：种子问题恒不在结果中（含 limit 窗口）。
- **边界**：`limit=1` 只取首项；`limit=0/11` → 422；无标签 → 空；不存在 → 404。

### 4.3 本轮缺陷

无产品缺陷。契约完整性测试按预期捕获端点计数漂移（17/19→18/20），已同步更新门禁期望值。

## 五、DoD 勾选

- [x] 六步法落地，仅触及本 Fxx 点名对象
- [x] 无表结构变更，无需迁移
- [x] 单元 + 集成测试已写入 `tests/`
- [x] `openapi.json` 重导出且 `--check` 一致
- [x] 本台账登记
- [x] `docs/PROGRESS.md` 变更记录登记
- [x] 门禁：ruff 0 / mypy 0 / coverage 82.85%（≥70%）/ domain 95%（≥90%）
- [x] 全量 pytest（含 integration）：**390 passed**（157.49s）
- [x] 未执行任何 commit/push

## 六、文档同步与观察

- `docs/api/api-contract-notes.md`：新增 related 端点口径
- `docs/PROGRESS.md`：变更记录新增本 Fxx 行
- 观察（未改，超出 F03 半径）：`README.md` 仍写「17 条路径 / 19 个操作」，与当前 18/20 不一致，建议后续统一更新
