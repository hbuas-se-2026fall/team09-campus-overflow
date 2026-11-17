# F09 核心读路径性能与搜索索引升级 · 开发与测试台账

> 日期：2026-11-17 · 上下文：`identity`（读路径合并）+ `qa`（搜索索引）· 依赖：F02 全文搜索、阶段 2 identity 仓储
> 裁定：D1 坚持单角色不变式（无角色行回退 `student`；多角色脏数据由 `one_or_none()` 抛 `MultipleResultsFound` → 500 记日志，不写断言 500 的测试，不提前改 `User.role` 集合）· D2 `questions.title`/`body` 建 `pg_trgm` GIN 索引，保持 F02 `ILIKE` + `escape_like` 完全兼容；`downgrade` 只 `DROP INDEX` 不删扩展 · D3 零 HTTP 契约变更
> 分支/工作区：`feat/f09-read-perf-and-trgm`（F09 改动未 commit）

## 一、交付范围

- `identity`：[repository.py](../../app/contexts/identity/infrastructure/repository.py) 将 `get_by_email` / `get_by_student_id` / `get_by_staff_id` / `get_by_id` 合并为单次 4 步 `outerjoin` 查询（`users → students → teachers → user_roles → roles`），由原来的每用户 4 条 SQL 压为 1 条 `SELECT`。
- `qa`：[models.py](../../app/contexts/qa/infrastructure/models.py) 与迁移 [ef84c7f8187e_add_questions_trgm_indexes_f09.py](../../alembic/versions/ef84c7f8187e_add_questions_trgm_indexes_f09.py) 为 `questions` 启用 `pg_trgm` 扩展并建立 `ix_questions_title_trgm`、`ix_questions_body_trgm`（`gin_trgm_ops`）。
- **不改 HTTP 契约**：路径、参数、状态码与响应字段均不变。

明确不做：不引入 `tsvector` / 中文分词；不提前为 F15 改写 `User.role` 为多角色集合；不使用 `CREATE INDEX CONCURRENTLY`（课程规模下 `CREATE INDEX` 短时锁写可接受）；不改前端。

## 二、六步法改动清单

| 步骤 | 文件 | 改动 |
|:--|:--|:--|
| 1 domain | 无 | 维持既有 `User`、`UserRepository`、`QuestionFilter` |
| 2 application | 无 | 维持既有 `identity` 与 `qa` 用例 |
| 3 infrastructure | `app/contexts/identity/infrastructure/repository.py`、`app/contexts/qa/infrastructure/models.py`、`alembic/versions/ef84c7f8187e_add_questions_trgm_indexes_f09.py` | 抽取 `_user_select()` 显式 4 步 `outerjoin` 与纯同步 `_row_to_domain()`（`one_or_none()`）；`QuestionModel.__table_args__` 声明双 GIN 索引防漂移；Alembic 迁移创建 `pg_trgm` 扩展与索引 |
| 4 interfaces | 无 | 零接口层改动 |
| 5 tests | `tests/contexts/identity/infrastructure/test_repository.py` | 新增 `test_read_methods_issue_single_user_select`（`before_cursor_execute` 断言 4 条读路径各自仅 1 条含 `FROM USERS` 的 `SELECT`）与 `test_missing_user_role_row_falls_back_to_student` |
| 6 收口 | 本台账、`docs/PROGRESS.md`、`README.md` | 记录迁移往返、`alembic check` 零漂移、`EXPLAIN` 与全套门禁实测 |

### 关键设计

- **完整 join 链**：`UserModel` → `outerjoin StudentModel` → `outerjoin TeacherModel` → `outerjoin UserRoleModel` → `outerjoin RoleModel`，避免漏经 `user_roles` 造成笛卡尔积；取整行后改为 `.one_or_none()`（而非只取首列的 `scalar_one_or_none()`）。
- **SQL 计数测试防假失败**：`before_cursor_execute` 挂在 `engine.sync_engine` 上并在 `try ... finally` 中 `event.remove`，仅统计以 `SELECT` 开头且含 `FROM USERS` 的语句，排除 `BEGIN` / `SELECT 1` 干扰，避免污染同进程其他测试。
- **索引漂移与扩展边界**：在 `QuestionModel.__table_args__` 同步声明 `postgresql_using="gin"` 与 `postgresql_ops={"title"/"body": "gin_trgm_ops"}`，升级后 `alembic check` 确认零漂移；`downgrade()` 只删两个索引不删 `pg_trgm` 扩展。

## 三、门禁实测（2026-11-17）

| 门禁 | 命令 | 结果 |
|:--|:--|:--|
| Lint | `ruff check .` | `All checks passed!` |
| 类型 | `mypy app` | `Success: no issues found in 135 source files` |
| 单元 + 总覆盖率 | `pytest -m "not integration" --cov=app --cov-report=term-missing --cov-fail-under=70 -q` | **298 passed**, 184 deselected；TOTAL **83.40%** |
| 核心聚合覆盖率 | `python -m coverage report --include="*/domain/*" --fail-under=90` | **94%** |
| 契约防漂移 | `python scripts/export_openapi.py --check` | `openapi.json 与当前代码一致` |
| 全量集成 | `pytest -m integration -q` | **184 passed**, 298 deselected（测试清理修复后复跑 242.51s） |
| 迁移往返 | `alembic upgrade head` → `alembic downgrade 6360fb6b24dd` → `alembic upgrade head` → `alembic current` | `6360fb6b24dd` → `ef84c7f8187e` → `6360fb6b24dd` → `ef84c7f8187e (head)` |
| 迁移漂移 | `alembic check` | `No new upgrade operations detected.` |

### 3.1 EXPLAIN 实证（`questions` 共 3,378 行，`pg_trgm 1.6`）

在 `SET LOCAL enable_seqscan = off` 下执行 F02 同款 `ILIKE '%postgresql%' ESCAPE '\'` 检索实测：

```text
Bitmap Heap Scan on questions  (cost=147.59..213.63 rows=70 width=16) (actual time=0.423..0.498 rows=68 loops=1)
  Recheck Cond: (((title)::text ~~* '%postgresql%'::text) OR (body ~~* '%postgresql%'::text))
  Heap Blocks: exact=24
  Buffers: shared hit=58
  ->  BitmapOr  (cost=147.59..147.59 rows=70 width=0) (actual time=0.411..0.411 rows=0 loops=1)
        Buffers: shared hit=34
        ->  Bitmap Index Scan on ix_questions_title_trgm  (cost=0.00..74.01 rows=69 width=0) (actual time=0.247..0.247 rows=68 loops=1)
              Index Cond: ((title)::text ~~* '%postgresql%'::text)
              Buffers: shared hit=17
        ->  Bitmap Index Scan on ix_questions_body_trgm  (cost=0.00..73.55 rows=1 width=0) (actual time=0.131..0.131 rows=1 loops=1)
              Index Cond: (body ~~* '%postgresql%'::text)
              Buffers: shared hit=17
Execution Time: 0.826 ms
```

单列检索 `WHERE title ILIKE '%postgresql%' ESCAPE '\'` 走 `Bitmap Index Scan on ix_questions_title_trgm`（`Execution Time: 0.175 ms`）。说明：1–2 字符短关键词与 `%`/`_`/`\` 转义查询在 PG 下仍由原有语义兼容兜底，全量 F02 仓储与 API 集成测试均已回归通过。

## 四、测试覆盖

| 文件 | 条数 | 覆盖点 |
|:--|:--|:--|
| `tests/contexts/identity/infrastructure/test_repository.py` | 6（新增 2） | 四条读路径（email/student_id/staff_id/id）各仅发 1 条含 `FROM USERS` 的 `SELECT`；无 `user_roles` 行时回退 `student` 角色，并在 `finally` 删除该测试用户，避免污染后续集成测试 |
| 全量 F02 回归（`test_question_repository.py` / `test_question_api.py`） | 全量纳入 `184 passed` | `pg_trgm` 安装后标题/正文 `ILIKE`、大小写、通配符转义与组合筛选零回归 |

## 五、DoD 勾选

- [x] 六步法落地，仅触及 F09 点名对象，`test_architecture.py` 全绿
- [x] 迁移已人工审阅并完成 `down → up` 往返验证，且 `alembic check` 零漂移
- [x] 集成测试与 `EXPLAIN` 实证写入 `tests/` 与本台账并实测通过
- [x] `openapi.json` 未变更，`--check` 一致
- [x] 本台账与 `docs/PROGRESS.md`、`README.md` 已登记
- [x] 本地六道门禁 + 架构/契约测试全绿
- [x] 未执行任何 commit/push
