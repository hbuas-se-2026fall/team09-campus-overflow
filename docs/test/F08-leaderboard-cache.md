# F08 排行榜索引与热榜缓存 · 开发与测试台账

> 日期：2026-11-17 · 上下文：reputation · 依赖：F05 排行榜、声誉流水与 Celery 落账
> 裁定：D1 覆盖索引 `(occurred_at, user_id) INCLUDE (delta)` · D2 缓存端口只收领域参数、Key/序列化留在 infrastructure · D3 TTL 60s、最大陈旧 = TTL + Celery 延迟 · D4 Redis 故障降级直查 PG
> 分支/工作区：当前工作区（F08 改动未 commit）

## 一、交付范围

- `reputation_ledgers` 新增覆盖索引 `ix_reputation_occurred_user_inc_delta`；
- `GET /api/v1/leaderboard` 接入 Redis 短时缓存，命中直接返回，未命中回源并回写；
- Redis 连接失败、命令失败、非法客户端工厂、损坏 JSON 一律 warning 后降级直查 PG，不把排行榜打成 503；
- **不改 HTTP 契约**：响应字段、状态码、路径均不变。

明确不做：物化表/增量计数列、投票/采纳时主动删缓存、`CREATE INDEX CONCURRENTLY`、前端排行页与展示名（展示名待 F11）。

## 二、六步法改动清单

| 步骤 | 文件 | 改动 |
|:--|:--|:--|
| 1 domain | 无 | 复用既有 `LeaderboardPeriod` / `LeaderboardRow` / `resolve_period_range` |
| 2 application | `app/contexts/reputation/application/ports.py`、`get_leaderboard_use_case.py` | 新增 `LeaderboardCache` Protocol；用例注入可选 cache 与 TTL，命中 `[]` 不回源，未命中回源后回写 |
| 3 infrastructure | `app/contexts/reputation/infrastructure/models.py`、`leaderboard_cache.py`、`alembic/versions/6360fb6b24dd_add_reputation_leaderboard_index_f08.py` | 覆盖索引；Redis 适配器（Key `v1:leaderboard:{period}:{limit}:{start_utc_iso}`、JSON 序列化、异常降级）；迁移 |
| 4 interfaces | `app/contexts/reputation/interfaces/api/deps.py`、`routes.py`、`app/config/settings.py` | `LeaderboardCacheDep` 组合根；路由注入配置 TTL；新增 `leaderboard_cache_ttl_seconds=60` |
| 5 tests | `tests/contexts/reputation/application/test_get_leaderboard.py`、`infrastructure/test_leaderboard_cache.py`、`interfaces/test_leaderboard_api.py` | 应用缓存分支 4 条、适配器 6 条、API 集成 2 条 |
| 6 收口 | 本台账、`docs/api/api-contract-notes.md`、`docs/PROGRESS.md` | 记录最大陈旧口径与迁移/门禁实测 |

### 关键设计

- **索引证据**：窄窗口（2026-11-17 单日）在 `VACUUM (ANALYZE)` 后为 `Index Only Scan using ix_reputation_occurred_user_inc_delta`，`Heap Fetches: 0`；宽窗口 planner 选择 `Bitmap Index Scan`，仍使用该索引。聚合复杂度仍是窗口内流水行数 O(N)，索引消除的是回表/全表扫描，不改变聚合复杂度。
- **缓存语义**：`get()` 返回 `None` 表示未命中/降级，返回 `[]` 表示已缓存空榜；`set()` 非正 TTL 直接跳过。
- **Key 单源**：Key 含版本号与 UTC `start`，跨零点/周一/月初/学期边界自然换 Key，不会在 TTL 内串上一周期旧榜。
- **降级边界**：`get()` 捕获 `RedisError` / `OSError` / `ValueError` / `TypeError`（含非法 `redis_url`）；反序列化额外捕获损坏 JSON、`KeyError`、`TypeError`、`ValueError`；`set()` 失败仅 warning。
- **一致性口径**：不做写时主动清缓存；最大陈旧 = `leaderboard_cache_ttl_seconds`（60s）+ Celery 落账延迟（亚秒~约 1.3s）。

## 三、门禁实测（2026-11-17）

| 门禁 | 命令 | 结果 |
|:--|:--|:--|
| Lint | `ruff check .` | `All checks passed!` |
| 类型 | `mypy app` | `Success: no issues found in 135 source files` |
| 单元 + 总覆盖率 | `pytest -m "not integration" --cov=app --cov-report=term-missing --cov-fail-under=70 -q` | **298 passed**, 182 deselected；TOTAL **83.25%**；`leaderboard_cache.py` 98%，`get_leaderboard_use_case.py` 100% |
| 核心聚合覆盖率 | `python -m coverage report --include="*/domain/*" --fail-under=90` | **94%** |
| 契约防漂移 | `python scripts/export_openapi.py --check` | `openapi.json 与当前代码一致` |
| 架构/契约/声誉单测 | `pytest tests/test_architecture.py tests/test_contract.py tests/contexts/reputation -m "not integration" -q` | **54 passed**, 17 deselected |
| 全量集成 | `pytest -m integration -q` | **182 passed**, 298 deselected（248.29s） |
| 迁移往返 | `alembic downgrade 29caa98ef40a` → `alembic upgrade head` → `alembic current` | `29caa98ef40a` → `6360fb6b24dd`；当前 `6360fb6b24dd (head)` |
| 迁移漂移 | `alembic check` | `No new upgrade operations detected.` |

### 3.1 迁移与索引实证

```text
CREATE INDEX ix_reputation_occurred_user_inc_delta
ON public.reputation_ledgers USING btree (occurred_at, user_id)
INCLUDE (delta)
```

离线 SQL 验证：`upgrade 29caa98ef40a:6360fb6b24dd --sql` 生成上述 `CREATE INDEX`；
`downgrade 6360fb6b24dd:29caa98ef40a --sql` 生成 `DROP INDEX ix_reputation_occurred_user_inc_delta;`。
真实库 `downgrade → upgrade` 往返通过；`downgrade` 中已移除对 `DROP INDEX` 无意义的 `postgresql_include` 参数。

### 3.2 EXPLAIN 摘要

```text
Index Only Scan using ix_reputation_occurred_user_inc_delta on reputation_ledgers
  Index Cond: ((occurred_at >= '2026-11-17 00:00:00+00') AND (occurred_at < '2026-11-18 00:00:00+00'))
  Heap Fetches: 0
```

说明：该结果在 `VACUUM (ANALYZE) reputation_ledgers` 后取得；更宽时间窗口下 planner 选择
`Bitmap Index Scan on ix_reputation_occurred_user_inc_delta`，属于同索引的另一种访问路径。

## 四、测试覆盖

| 文件 | 条数 | 覆盖点 |
|:--|:--|:--|
| `tests/contexts/reputation/application/test_get_leaderboard.py` | 6（新增 4） | 缓存 miss→回源→回写、hit 不查仓储、`[]` 空榜命中、跨周期 `start` 隔离、`ttl<=0` 绕过 |
| `tests/contexts/reputation/infrastructure/test_leaderboard_cache.py` | 6（新建） | 序列化往返与空榜区分、上海/UTC 归一、损坏 JSON/非法 UUID/bool 分值降级、RedisError 降级、非正 TTL、客户端工厂 `ValueError` 降级 |
| `tests/contexts/reputation/interfaces/test_leaderboard_api.py` | 5（新增 2 集成） | TTL 内删库仍命中缓存、Redis 故障降级直查 PG 返回 200；原有公开榜单/窗口排除/非法参数回归 |

## 五、DoD 勾选

- [x] 六步法落地，仅触及 F08 点名对象，`test_architecture.py` 全绿
- [x] 迁移已人工审阅并完成 `down → up` 往返验证
- [x] 单元 + 集成测试写入 `tests/` 并实测通过
- [x] `openapi.json` 未变更，`--check` 一致
- [x] 本台账与 `docs/PROGRESS.md`、`docs/api/api-contract-notes.md` 已登记
- [x] 本地六道门禁 + 架构/契约测试全绿
- [x] 未执行任何 commit/push
