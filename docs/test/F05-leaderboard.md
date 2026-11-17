# F05 排行榜（周/月/学期）· 开发与测试台账

> 日期：2026-11-13 · 上下文：reputation · 依赖：声誉流水（已存在）
> 裁定：D8 净得分（含负）· D9 同分同名次（competition ranking）· D10 学期：春 3/1–8/1、秋 9/1–次年 2/1，2 月归上一秋季、8 月归当年春季
> 分支/工作区：`feat/question-filter` 工作树（叠加 F02/F03 未提交改动），未 commit

## 一、交付范围

新增 `GET /api/v1/leaderboard`（公开，无需登录）：

| 项 | 口径 |
|:--|:--|
| `period` | `week` / `month` / `semester`，默认 `week` |
| 区间 | 左闭右开；周=周一 00:00 起、月=1 日 00:00 起；学期按 D10 |
| 时区 | 边界按 `Asia/Shanghai` 计算后转 UTC 查询 |
| 得分 | 期间 `SUM(delta)` 净得分，含负（D8） |
| 名次 | `RANK()` 同分同名次（1,1,3）；同分按 `user_id` 升序稳定（D9） |
| `limit` | 1~100，默认 10；越界/非法 period → 422 |
| 空榜 | 200 + `entries=[]` |

明确不做：前端排行页、缓存/CDN、课程维度榜、展示名（待 F11，首版只给 `user_id`）。

## 二、六步法改动清单

| 步骤 | 文件 | 改动 |
|:--|:--|:--|
| 1 domain | `app/contexts/reputation/domain/leaderboard.py` | 新增 `LeaderboardPeriod`、`LeaderboardRow`、`resolve_period_range`（D10 边界单源） |
| 2 application | `app/contexts/reputation/application/get_leaderboard_use_case.py` | 只读用例：解析周期 → 委托仓储 Top N |
| 3 infrastructure | `app/contexts/reputation/domain/repository.py`、`infrastructure/repository.py` | 端口 +`list_top(start,end,limit)`；SQL `SUM(delta)` + `RANK() OVER` + 窗口过滤 + `LIMIT` |
| 4 interfaces | `app/contexts/reputation/interfaces/api/routes.py`、`schemas.py`、`main.py` | 新增公开 `leaderboard_router`；响应 schema 白名单；装配 |
| 5 tests | 见第四节 | domain 13 / application 2 / 仓储集成 4 / API 集成 3 |
| 6 收口 | 契约 + 文档 | `openapi.json` 重导出（**19 paths / 21 ops**）`--check` 一致；契约说明、台账、PROGRESS |

### 关键设计

- **零迁移**：`ix_reputation_user_occurred(user_id, occurred_at)` 已存在，覆盖按用户/时间聚合。
- **名次在 SQL**：`RANK() OVER (ORDER BY SUM(delta) DESC)` 一次查询完成聚合与名次，Python 侧不做二次排序。
- **边界单源**：`resolve_period_range` 是唯一学期/周/月边界实现，路由与用例不重复计算。

## 三、门禁实测（2026-11-13，定向）

| 门禁 | 命令 | 结果 |
|:--|:--|:--|
| Lint | `ruff check .` | All checks passed（0） |
| 类型 | `mypy app` | 0 errors（**103 文件**） |
| 定向测试 | `pytest tests/contexts/reputation tests/test_contract.py` | **51 passed** |
| 契约导出 | `scripts/export_openapi.py` + `--check` | 一致（**19 paths / 21 operations**） |
| 全量（含 integration） | `pytest -q` ×2 | 修复测试隔离后连跑两遍：**457 passed（234.85s）** / **457 passed（228.49s）** |

### 3.1 复跑可重现性记录（2026-11-13）

- 独立复跑首次：**456 passed / 1 failed（206.02s）**，失败为 `test_leaderboard_public_top_and_competition_rank` 的 `assert 4 == 1`。
- 根因（测试隔离，非产品缺陷）：原防干扰策略 `base_score = 10_000_000 + uuid4() % 1_000_000` **不保证单调**；上一轮全量遗留 3 个 10M 量级种子用户，本轮随机基座低于它们时 `high` 被压到第 4 名。
- 修复（仅测试文件）：
  1. 单调基座 `base_score = 10_000_000 + int(now.timestamp())`，时间恒增，本轮分值必然压过历史轮；
  2. `finally` 按 `event_id` 删除本轮 3 条种子流水，覆盖同秒双跑等极端情形。
- 复验：修复后全量**连跑两遍均 457 passed**（234.85s / 228.49s）。
- 如实记录：**“457 passed”首轮仅在当时库状态下成立；修复前不具备复跑可重现性**。

## 四、测试覆盖

| 文件 | 条数 | 覆盖点 |
|:--|:--|:--|
| `tests/contexts/reputation/domain/test_leaderboard.py` | 13 | 周（周三/周一零点/周日末）、月（月中/月末/跨年）、学期（春始/春末/8 月/秋始/年末/1 月/2 月） |
| `tests/contexts/reputation/application/test_get_leaderboard.py` | 2 | 周期解析与 limit 委托；空榜 |
| `tests/contexts/reputation/infrastructure/test_ledger_repository.py` | 4 | 期间聚合、同分同名次、窗口外排除、空窗口、limit |
| `tests/contexts/reputation/interfaces/test_leaderboard_api.py` | 3 | 公开访问 + Top/同分名次、limit=1、窗口外排除、非法参数 422 |

## 五、DoD 勾选

- [x] 六步法落地，仅触及本 Fxx 点名对象
- [x] 无表结构变更，无需迁移
- [x] 单元 + 集成测试已写入
- [x] `openapi.json` 重导出且 `--check` 一致
- [x] 本台账登记
- [x] `docs/PROGRESS.md` 变更记录登记
- [x] 定向门禁全绿（ruff / mypy / 51 passed）
- [x] 全量 pytest：修复隔离后连跑两遍 **457 passed**（234.85s / 228.49s）
- [x] 未执行任何 commit/push
