# F06 徽章体系 · 开发与测试台账

> 日期：2026-11-13 · 上下文：qa（统计）+ identity（用户存在性）· 依赖：无
> 裁定：D11 活跃=发帖/回答/评论/投票（不含登录）· D14 历史最长连续活跃天数（成就语义，不随断签消失）
> 分支/工作区：`feat/question-filter` 工作树（叠加 F02/F03/F05 未提交改动），未 commit

## 一、交付范围

新增公开端点 `GET /api/v1/users/{user_id}/badges`，实时计算，不物化：

| 徽章族 | 阈值（铜/银/金） | 口径 |
|:--|:--|:--|
| 回答数 | 5 / 20 / 50 | `answers` 中该用户回答总数 |
| 采纳率 | 50% / 70% / 90% | 回答数 ≥5 才评估；被采纳数 / 回答数；分母 0 不评估 |
| 连续活跃 | 3 / 7 / 30 天 | **历史最长**连续活跃天数；活跃日按 Asia/Shanghai 自然日，四类行为 UNION 去重 |

响应：`user_id`、`answer_count`、`accepted_count`、`acceptance_rate`、`longest_streak_days`、`badges[]`（`code/kind/tier/threshold`）。
用户不存在 → 404；无活动 → 200 + 空徽章。

明确不做：徽章图标资源、前端展示、授予通知、物化表、软删除联动（F13 后统一回改统计口径）。

## 二、六步法改动清单

| 步骤 | 文件 | 改动 |
|:--|:--|:--|
| 1 domain | `app/contexts/qa/domain/badges.py` | 徽章规则常量、`Badge`、`longest_active_streak`、`evaluate_badges` |
| 2 application | `app/contexts/qa/application/get_user_badges_use_case.py` | 只读用例：回答统计 + 活跃日 → 视图 |
| 3 infrastructure | `app/contexts/qa/domain/repository.py`、`infrastructure/user_activity_repository.py` | 新端口 `UserActivityRepository`；`answer_stats`（COUNT + FILTER）与 `active_dates`（四表 UNION，`timezone('Asia/Shanghai')::date`） |
| 4 interfaces | `app/contexts/qa/interfaces/api/badges.py`、`schemas.py`、`deps.py`、`routes.py`、`main.py` | 公开路由；用户存在性经 identity interfaces `UserRepo` 校验；组合根装配 |
| 5 tests | 见第四节 | domain 7 / application 2 / 仓储集成 4 / API 集成 3 |
| 6 收口 | 契约 + 文档 | `openapi.json` 重导出（**20 paths / 22 ops**）`--check` 一致；契约说明、台账、PROGRESS |

### 关键设计

- **零迁移**：纯读聚合，`answers`/`questions`/`comments`/`votes` 既有索引足够。
- **时区单源**：活跃日全部在 SQL 用 `Asia/Shanghai` 截断，避免 Python 侧重复换算。
- **可达性**：回答数 <5 不评估采纳率，避免 1/1 满分刷徽章；分母 0 直接不评估。
- **徽章语义**：连续活跃取历史最长，断签不丢徽章（D14）。

## 三、门禁实测（2026-11-13，定向）

| 门禁 | 命令 | 结果 |
|:--|:--|:--|
| Lint | `ruff check .` | All checks passed（0） |
| 类型 | `mypy app` | 0 errors（**107 文件**） |
| 定向测试 | `pytest`（F06 四文件 + 契约） | **23 passed** |
| 契约导出 | `scripts/export_openapi.py` + `--check` | 一致（**20 paths / 22 operations**） |
| 全量（含 integration） | `pytest -q` | **457 passed**（195.90s，F03–F07 全量） |

## 四、测试覆盖

| 文件 | 条数 | 覆盖点 |
|:--|:--|:--|
| `tests/contexts/qa/domain/test_badges.py` | 7 | 空/最长/去重与断档；回答数 4/5/20/50；采纳率分母 <5 与 0；采纳率 40/50/70/90%；连续 2/3/7/30 |
| `tests/contexts/qa/application/test_get_user_badges.py` | 2 | 统计+规则组装（5 答 3 采纳 3 连击）；零活动空徽章 |
| `tests/contexts/qa/infrastructure/test_user_activity_repository.py` | 4 | 回答数/采纳数；四类行为活跃日 UNION；上海自然日边界（UTC 16:30→次日）；零活动 |
| `tests/contexts/qa/interfaces/test_badges_api.py` | 3 | 公开 + 3 连击 `streak_3`；无活动空；不存在 404 |

## 五、DoD 勾选

- [x] 六步法落地，仅触及本 Fxx 点名对象
- [x] 无表结构变更，无需迁移
- [x] 单元 + 集成测试已写入
- [x] `openapi.json` 重导出且 `--check` 一致
- [x] 本台账登记
- [x] `docs/PROGRESS.md` 变更记录登记
- [x] 定向门禁全绿（ruff / mypy / 23 passed）
- [x] 全量 pytest：**457 passed**（195.90s）
- [x] 未执行任何 commit/push
