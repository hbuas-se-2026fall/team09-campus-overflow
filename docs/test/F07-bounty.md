# F07 教师悬赏 · 开发与测试台账

> 日期：2026-11-13 · 上下文：qa（积分 + 悬赏，与采纳/关闭同事务）· 依赖：教师角色、采纳/关闭用例
> 裁定：D12 积分账本 + `question_bounties` 均落 qa；来源=教师注册初始额度常量（100），首版不做发放端点 · D13 同题仅一个有效悬赏；关闭未采纳全额退款；采纳结算一次
> 分支/工作区：`feat/question-filter` 工作树（叠加 F02–F06 未提交改动），未 commit

## 一、交付范围

| 端点 | 语义 |
|:--|:--|
| `POST /api/v1/questions/{id}/bounty` | 仅教师；body `{amount: 1~1,000,000}`；问题须存在且 open；余额不足/已有 open 悬赏 409 |
| `GET /api/v1/questions/{id}/bounty` | 公开；返回进行中悬赏，无则 `null`；问题不存在 404 |

资金流：
- **发起**：惰性开户（教师初始 100 分）→ 条件扣减余额（`balance >= amount`）→ 插入 open 悬赏 → 写冻结流水（`source=bounty, event_id=bounty_id, delta=-amount`），同事务。
- **采纳**：`AcceptAnswerUseCase` 同事务 `open→settled` 条件更新（只成功一次）→ 答主入账 + 流水 `bounty_award`。
- **关闭未采纳**：`CloseQuestionUseCase` 同事务 `open→refunded` → 教师全额入账 + 流水 `bounty_refund`。
- 积分与声誉完全分离，不共用 `reputation_ledgers`。

明确不做：前端悬赏 UI、积分充值/提现、管理员发放端点、悬赏叠加、排行榜联动。

## 二、六步法改动清单

| 步骤 | 文件 | 改动 |
|:--|:--|:--|
| 1 domain | `qa/domain/bounty.py`、`errors.py`、`repository.py` | `Bounty`/`BountyStatus`/`PointsEntry`/`INITIAL_TEACHER_POINTS`；`InsufficientPointsError`/`BountyAlreadyActiveError`；`PointsRepository`/`BountyRepository` 端口 |
| 2 application | `bounty_service.py`、`create_bounty_use_case.py`、`get_bounty_use_case.py`、`commands.py` | 创建/结算/退款编排；发起与查询用例；`CreateBountyCommand` |
| 3 infrastructure | `qa/infrastructure/models.py`、`points_repository.py`、`bounty_repository.py` | 三表 + 索引；惰性开户/条件扣减/入账/幂等流水；部分唯一索引 + 条件状态迁移 |
| 4 interfaces | `qa/interfaces/api/bounty.py`、`schemas.py`、`deps.py`、`routes.py`、`main.py`；`questions.py`/`answers.py` | 两个端点（路由层教师 403）；采纳/关闭注入 `BountyService` |
| 5 tests | 见第四节 | service 5 / 仓储集成 5 / API 集成 3 |
| 6 收口 | 迁移 + 契约 + 文档 | `alembic revision --autogenerate` 生成 `29caa98ef40a`（已审并 apply）；`openapi.json` 25 paths/28 ops；台账/PROGRESS |

### 关键设计

- **并发安全**：同题 open 悬赏由部分唯一索引 `uq_question_bounties_open` 兜底；结算/退款用 `WHERE status='open'` 条件 UPDATE，并发下恰一次；流水 `(source, event_id)` 唯一二次兜底。
- **库层余额兜底**：`points_accounts.balance CHECK (balance >= 0)`——应用层条件扣减之外，任何路径都不能把余额写成负数。
- **原子性**：扣减、悬赏插入、冻结流水同事务；插入失败（重复悬赏）整体回滚，余额自动恢复。
- **惰性开户**：`INSERT ... ON CONFLICT DO NOTHING RETURNING` 判定是否首次；仅首次写 `grant` 流水，并发首次访问不会双送分。
- **学生入账**：`credit` 以 0 余额开户，不发放教师初始额度。

## 三、门禁实测（2026-11-13，定向）

| 门禁 | 命令 | 结果 |
|:--|:--|:--|
| Lint | `ruff check .` | All checks passed（0） |
| 类型 | `mypy app` | 0 errors（**132 文件**） |
| 单元（CI 口径） | `pytest -m "not integration" -q` | **281 passed**（174 deselected） |
| 契约导出 | `scripts/export_openapi.py` | **25 paths / 28 operations** |
| 迁移 | `alembic revision --autogenerate`（scratch 库） | 生成 `29caa98ef40a_add_points_and_bounty_tables_f07.py`（含 balance CHECK）；**已审核并 apply（2026-11-13）** |
| 全量（含 integration） | `pytest -q` | **457 passed**（195.90s，F03–F07 全量） |

## 四、测试覆盖

| 文件 | 条数 | 覆盖点 |
|:--|:--|:--|
| `tests/contexts/qa/application/test_bounty_service.py` | 5 | 冻结扣分+流水；余额不足；重复 open 冲突；结算只一次；退款只一次 |
| `tests/contexts/qa/infrastructure/test_points_bounty_repository.py` | 5 | 开户幂等+授予仅一次+条件扣减；学生入账 0 开户；唯一 open + 条件状态迁移 + 结算后可再发；**2 路并发结算/退款各恰一次（asyncio.gather）** |
| `tests/contexts/qa/interfaces/test_bounty_api.py` | 3 | 学生 403/发起/查询/重复 409/余额不足 409/采纳结算+答主余额；关闭退款恢复余额；不存在问题 404 |

## 五、DoD 勾选

- [x] 六步法落地，仅触及本 Fxx 点名对象
- [x] 迁移已人工审核并应用：`29caa98ef40a`（2026-11-13，含 balance CHECK）
- [x] 单元 + 集成测试已写入
- [x] `openapi.json` 重导出
- [x] 本台账登记
- [x] `docs/PROGRESS.md` 变更记录登记
- [x] 定向门禁全绿（ruff / mypy / 281 单测）
- [x] 全量 pytest：**457 passed**（195.90s）
- [x] 未执行任何 commit/push

## 六、2026-11-17 Bug 修复：并发行锁 + 已采纳拦截 + 个人积分端点

- **并发与不变式修复**：
  - `QuestionRepository.get_by_id(question_id, *, for_update=False)` 支持 `with_for_update().execution_options(populate_existing=True)`；
  - `CreateBountyUseCase`、`CloseQuestionUseCase`、`AcceptAnswerUseCase` 统一加行锁读取问题，串行化悬赏/关闭/采纳并发；
  - `CreateBountyUseCase` 新增 `question.accepted_answer_id is not None` 拦截（`AnswerAlreadyAcceptedError → 409`）。
- **个人积分闭环**：
  - `PointsRepository` 新增 `list_entries()`；新增 `GetMyPointsUseCase` 与 `GET /api/v1/users/me/points`（教师惰性开户 100 分，学生只读，流水含 `event_id`）。
- **新增测试**：
  - 单测：`test_create_bounty_use_case.py`（4 条）、`test_get_my_points_use_case.py`（3 条），全部通过；
  - 集成：`test_bounty_api.py` 新增 2 条（已采纳 409 + 并发发起×关闭竞态）、`test_points_api.py`（1 条全链路），均通过。
- **实测门禁**：`ruff 0` / `mypy 134 文件 0` / `export_openapi.py --check` 一致（26 paths / 29 ops）/ CI 单测 **288 passed**（82.90%，domain 94%）；集成 **180 passed**（249.89s）；全量 **468 passed**（254.62s）。补充环境：Docker Desktop 引擎拉起后，6379/6393 均落入 Windows 保留端口段，临时 Redis 容器使用随机宿主端口 1779；数据库迁移已在 head `29caa98ef40a`。
