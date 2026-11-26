# F15 RBAC 扩展与教师认证回答 · 开发与测试台账

> 日期：2026-11-25 · 上下文：`identity` + `qa` + `discovery` · 依赖：F04（站内通知）、F07（教师悬赏守卫）、F11（公开展示名）、F12（编辑回答）、F13（软删除与单根锁序）
> 裁定：D1 RBAC 角色扩展（`Role = Literal["student", "teacher", "ta", "admin"]`；`RegisterRequest` / `RegisterUseCase` 仍禁 `ta`/`admin` 422；`CurrentUser` 与 `require_roles` 继续基于 DB 每请求实时角色；变更角色保留 `students`/`teachers` 原登录句柄且 `user_roles` 严格唯一 1 行；新增 `GET /api/v1/admin/users` 与 `PATCH /api/v1/admin/users/{user_id}/role`，禁改本人 409、不存在 404，F07 悬赏仍仅 `teacher`）· D2 F11 展示面与 `AnswerResponse` 同步（`_ROLE_DISPLAY_PREFIXES` 补齐 `管理员`/`教师`/`助教`/`学生`；`_ROLE_PRIORITY` 定死 `admin=0, teacher=1, ta=2, student=3`；`Answer`/`AnswerModel`/`AnswerResponse` 增量暴露 `is_teacher_verified`、`verified_by_name`、`verified_at`；`_common.answer_response` 与 `hydrate_answer_response` 单源装配，详情 `get_question` 将 `a.verified_by` 并入单次 `get_summaries` IN 查询零 N+1）· D3 教师/助教/管理员认证回答（`POST /api/v1/answers/{answer_id}/verify` 幂等 200、`DELETE /api/v1/answers/{answer_id}/verify` 幂等 204；`require_roles("teacher", "ta", "admin")` 学生 403；单根无环锁序 + 条件 `UPDATE`；`NotificationType.ANSWER_VERIFIED = "answer_verified"` 仅首次变更且非自操作时同事务写入，不触发声誉变动）
> 分支/工作区：`feat/f15-rbac-and-verify`（已通过 Auditor #1.2 独立验收 PASS，待批准提交推送并 PR 合入 `main` 后封箱 `v1.1.0`）

## 一、交付范围

| 交付项 | 语义 |
|:--|:--|
| RBAC 角色扩展与 DB 实时鉴权 | `Role` 扩展至 `student` / `teacher` / `ta` / `admin`；自助注册端 `RegisterRequest` / `RegisterUseCase` 与 `User.register` 保持仅允许 `student`/`teacher`（传 `ta`/`admin` 返回 422）；角色变更不删 `students`/`teachers` 行，保留原学工号登录；`CurrentUser` 每请求查库读取实时角色，改角色后旧 Access Token 下次请求立即生效/失效 |
| `GET /api/v1/admin/users` | `require_roles("admin")`（未登录 401，非 admin 403）；Query `page >= 1`、`page_size` 1..100、`role` 可选；按 `created_at DESC, id DESC` 排序，响应 `{items, total, page, page_size, total_pages}`，`AdminUserItem` 绝不含 `password_hash` |
| `PATCH /api/v1/admin/users/{user_id}/role` | `require_roles("admin")`（未登录 401，非 admin 403）；请求体 `UpdateUserRoleRequest`（`extra="forbid"`）；禁止修改本人角色 **409** `"不可修改本人角色"`；目标不存在 **404** `"用户不存在"`；同角色变更幂等 **200** + `AdminUserItem` |
| `POST /api/v1/answers/{answer_id}/verify` | `require_roles("teacher", "ta", "admin")`（未登录 401，学生 403）；首次认证置 `is_teacher_verified=true`、`verified_by`、`verified_at`，返回 **200 + `AnswerResponse`**（含真实 `votes`、`author_name`、`is_accepted`、`is_teacher_verified`、`verified_by_name`、`verified_at`、有序 `comments[]`）；重复认证幂等返回 200 并保持首次认证人与时间；已删 404、已关闭 409 |
| `DELETE /api/v1/answers/{answer_id}/verify` | `require_roles("teacher", "ta", "admin")`（未登录 401，学生 403）；清空认证状态并返回 **204**（未认证时幂等 **204**）；已删 404、已关闭 409 |
| 展示面与通知联动 | `_ROLE_DISPLAY_PREFIXES` 补齐 `助教`/`管理员`；`_ROLE_PRIORITY` 定死 `admin > teacher > ta > student`；`AnswerResponse` 增量暴露 3 字段并统一单源装配；`discovery` 新增 `NotificationType.ANSWER_VERIFIED = "answer_verified"`（零迁移），仅首次认证且非自操作时同事务写入（`target_type="answer"`, `target_id=answer.id`, `question_id=question.id`），**不触发声誉变动** |
| 数据库迁移与运维脚本 | 迁移 `0c58c26e2c45`（`roles` 幂等种子 `'ta'`、`'admin'`；`answers` 增 `is_teacher_verified`、`verified_by`、`verified_at` 及外键 `fk_answers_verified_by` `ON DELETE SET NULL`）；新增 `scripts/seed_admin.py`（从环境变量读取信息幂等初始化/提权管理员，零硬编码密码） |

明确不做（Non-Goals）：F07 悬赏向 `ta`/`admin` 扩权（保持仅 `teacher`）；助教代提问者采纳答案；认证回答触发声誉加分；前端页面修改。

## 二、六步法改动清单

| 步骤 | 文件 | 改动 |
|:--|:--|:--|
| 1 domain | `app/contexts/identity/domain/errors.py`、`user.py`、`repository.py`；`app/contexts/qa/domain/answer.py`、`repository.py`；`app/contexts/discovery/domain/notification.py` | 新增 `UserNotFoundError`/`SelfRoleChangeError`；扩展 `Role`、`_ROLE_DISPLAY_PREFIXES`、`User.change_role()`、`User.register()` 拒 `ta`/`admin`；`UserRepository` 增 `list_paginated`/`update_role`；`Answer` 增认证 3 字段及 `verify()`/`unverify()`，`AnswerRepository` 增 `update_verification()`；`NotificationType` 增 `ANSWER_VERIFIED` |
| 2 application | `app/contexts/identity/application/commands.py`、`queries.py`（新建）、`list_users_use_case.py`（新建）、`update_user_role_use_case.py`（新建）；`app/contexts/qa/application/commands.py`、`verify_answer_use_case.py`（新建） | 新增 `ListUsersQuery`/`UserPage`/`ListUsersUseCase`、`UpdateUserRoleCommand`/`UpdateUserRoleUseCase`、`VerifyAnswerCommand`/`UnverifyAnswerCommand`、`VerifyAnswerUseCase`/`UnverifyAnswerUseCase`（沿用 F13 单根无环锁序） |
| 3 infrastructure | `app/contexts/identity/infrastructure/models.py`、`repository.py`、`user_summary_reader.py`；`app/contexts/qa/infrastructure/models.py`、`answer_repository.py`；`alembic/versions/0c58c26e2c45_add_rbac_roles_and_answer_verification_.py`（新建）；`scripts/seed_admin.py`（新建） | `_ROLE_PRIORITY` 定死 4 角色序；`SqlAlchemyUserRepository` 实现 `list_paginated` 与 `update_role`（锁 `UserModel` 后原子替换 `user_roles` 唯一行）；`AnswerModel` 增 3 列与 `fk_answers_verified_by`；`SqlAlchemyAnswerRepository` 还原 3 字段并实现条件 `update_verification`（复用 `_active_open_question_exists` 与 `_raise_missing_or_closed`）；审核迁移脚本并补齐 `roles` 幂等种子 |
| 4 interfaces | `app/contexts/identity/interfaces/api/deps.py`、`error_mapping.py`、`schemas.py`、`admin_routes.py`（新建）；`app/contexts/qa/interfaces/api/schemas.py`、`_common.py`、`questions.py`、`answers.py`；`app/contexts/discovery/interfaces/api/schemas.py`；`app/main.py` | 注册 404/409 映射，挂载 `admin_router`，曝光 `AdminUser`/`AnswerVerifierUser`；`AnswerResponse` 增量暴露 3 字段并抽共用 `answer_response`/`hydrate_answer_response`（详情零 N+1）；`answers.py` 新增 `POST`/`DELETE /{answer_id}/verify` |
| 5 tests | 领域/用例/fake/仓储/API 并发/契约测试 | 同步 7 处 `FakeAnswerRepository`、4 处 `FakeUserRepository`、`test_answer_vote_api.py` 与 `test_edit_answer_api.py` 键集合；更新 `test_user.py`、`test_user_summary_role_resolution.py`、`test_answer.py`、`test_notification.py`；新建 `test_admin_users_use_cases.py`、`test_admin_users_unit.py`、`test_admin_user_repository.py`、`test_admin_users_api.py`、`test_verify_answer_use_case.py`、`test_verify_answer_unit.py`、`test_verify_answer_repository.py`、`test_verify_answer_api.py`；更新 `tests/test_contract.py` 至 `34 paths / 40 operations` |
| 6 收口 | `openapi.json`、本台账、`docs/PROGRESS.md`、`docs/plan/f-engineering-standard.md`、`README.md`、`docs/api/api-contract-notes.md` | 重导出契约过 `--check`，同步 5 份文档与 `v1.1.0` 阶段收口全量回归记录 |

### 关键设计与人工审核记录
- **迁移人工审核**：`alembic revision --autogenerate` 精确检出 `answers.is_teacher_verified`、`answers.verified_by`、`answers.verified_at` 与 `fk_answers_verified_by`（零多余索引/列漂移）；人工显式补齐 `INSERT INTO roles (name) VALUES ('ta'), ('admin') ON CONFLICT (name) DO NOTHING` 与对称 `downgrade`（先删外键与 3 列再 `DELETE FROM roles WHERE name IN ('ta', 'admin')`）。
- **并发与唯一不变式**：`update_role` 锁 `UserModel` 后执行 `DELETE user_roles` + `INSERT ON CONFLICT DO NOTHING`，保证多并发改角色后仍严格保持每用户唯一 1 行 `user_roles` 且保留 `students`/`teachers` 行；`VerifyAnswerUseCase` / `UnverifyAnswerUseCase` 沿用 `Answer -> Question(for_update=True) -> 重读 Answer -> ensure_open` 单根无环锁序，加库级条件 `UPDATE` 兜底并发关贴与软删除，确保并发重复认证仅写 1 条通知。

## 三、门禁与实测证据（2026-11-25）

| 检查项 | 命令 | 结果 |
|:--|:--|:--|
| Lint | `.venv\Scripts\ruff.exe check .` | `All checks passed!`（0 违规） |
| 严格类型检查 | `.venv\Scripts\mypy.exe app` | `Success: no issues found in 151 source files` |
| 契约导出与防漂移 | `.venv\Scripts\python.exe scripts/export_openapi.py --check` | `openapi.json 与当前代码一致`（**34 paths / 40 operations**） |
| 架构 + 契约测试 | `.venv\Scripts\pytest.exe tests/test_architecture.py tests/test_contract.py -q` | **17 passed**（8 条 AST 护栏 0 违规） |
| CI 单元回归 + 覆盖率 | `.venv\Scripts\pytest.exe -m "not integration" --cov=app --cov-report=term-missing --cov-fail-under=70 -q` | **407 passed**, 228 deselected；TOTAL **83.23%** |
| 核心聚合覆盖率 | `.venv\Scripts\python.exe -m coverage report --include="*/domain/*" --fail-under=90` | **94%**（`user.py`、`answer.py`、`errors.py`、`notification.py` 均 **100%**） |
| 隔离库迁移往返 | 独立临时库 `campus_mig_test` 执行 `f15_mig_roundtrip.py`（`upgrade head → downgrade -1 → upgrade head → check` + 库对象检查 + `DROP DATABASE`） | `0c58c26e2c45 (head)` → `609aeba713d3` → `0c58c26e2c45 (head)`；`No new upgrade operations detected.`；临时库已销毁 |
| 共享库备份与升级 | `docker exec campusoverflow-db-1 pg_dump -U campus campus > D:\a_work\_archive\db_backups\campus_pre_f15.sql`；`alembic upgrade head` / `current` / `check` | 备份 **9,077,348 B**（D 盘）；共享库平滑升至 `0c58c26e2c45 (head)`，`No new upgrade operations detected.` |
| F15 定向集成 + 并发 2 轮 | `pytest tests/contexts/identity/infrastructure/test_admin_user_repository.py tests/contexts/identity/interfaces/test_admin_users_api.py tests/contexts/qa/infrastructure/test_verify_answer_repository.py tests/contexts/qa/interfaces/test_verify_answer_api.py -q`（连续 2 轮） | Builder：第 1 轮 **10 passed**（41.91s）/ 第 2 轮 **10 passed**（43.12s）；Auditor #1.2 复测：**10 passed × 2**（43.26s / 44.33s） |
| 跨模块关联回归（Auditor #1.2） | `test_answer_vote_api.py`、`test_edit_answer_api.py`、`test_f11_display_name_and_profile_api.py`、`test_bounty_api.py`、`test_notification_api.py` | **25 passed**（75.04s） |
| `scripts/seed_admin.py` 验证 | 环境变量传入测试管理员并连跑两次 + 清理临时测试行 | Builder 与 Auditor #1.2 均实测首次创建、二次幂等跳过 |
| `v1.1.0` 收口全量集成回归 | `.venv\Scripts\pytest.exe -m integration -q` | **228 passed**, 407 deselected（421.33s / 0:07:01，F01–F15 全量真库回归零失败；合计 407 + 228 = **635 passed**） |
| 真实进程端到端冒烟（Auditor #1.2） | 真实 `uvicorn app.main:app`（`127.0.0.1:18125`）+ `celery worker --pool=solo` 连真实 PG `15432` + Redis `16379` | **75 HTTP 请求全绿**，Uvicorn/Celery 日志零 500 / 零未捕获 Traceback，临时数据 0 残留 |

### 测试数据知识来源（遵循真实知识测试数据规范）
- PostgreSQL Concurrency Control & MVCC（快照可见性、B-link 并发查找、2PL）：`https://www.postgresql.org/docs/current/mvcc.html`
- Operating Systems: Three Easy Pieces（Clock 页面置换、拥塞控制与页表/TLB）：`https://pages.cs.wisc.edu/~remzi/OSTEP/`

## 四、测试覆盖

| 文件 | 改动 | 覆盖点 |
|:--|:--|:--|
| `tests/contexts/identity/domain/test_user.py` | +3 单测 + 同步前缀断言 | `ta`/`admin` 展示前缀、禁止直接注册 `ta`/`admin`、`User.change_role` 保留学工号与未知角色 422 |
| `tests/contexts/identity/infrastructure/test_user_summary_role_resolution.py` | 更新优先级断言 | `_ROLE_PRIORITY` `admin > teacher > ta > student > 未知角色` |
| `tests/contexts/qa/domain/test_answer.py` | +1 综合单测 | `Answer.verify()`/`unverify()` 幂等性、`edit_body`/`accept` 保留既有认证状态 |
| `tests/contexts/discovery/domain/test_notification.py` | +1 单测 + 枚举断言 | `NotificationType.ANSWER_VERIFIED`（≤20 字符）与 `build_notification` |
| `tests/contexts/identity/application/test_admin_users_use_cases.py` | +5 单测（新建） | `ListUsersUseCase` 分页/排序/角色筛选、`UpdateUserRoleUseCase` 禁改本人 409 / 404 / 幂等、`RegisterRequest` 422 |
| `tests/contexts/identity/interfaces/test_admin_users_unit.py` | +4 单测（新建） | 管理员路由鉴权矩阵（`student`/`teacher`/`ta` 403）与 `admin_routes` 响应装配 |
| `tests/contexts/qa/application/test_verify_answer_use_case.py` | +4 单测（新建） | `VerifyAnswerUseCase` / `UnverifyAnswerUseCase` 锁序、重复幂等不重发通知、自操作跳过、404/409 分支 |
| `tests/contexts/qa/interfaces/test_verify_answer_unit.py` | +4 单测（新建） | `POST`/`DELETE /verify` 角色门禁（学生 403、`teacher`/`ta`/`admin` 200/204）与 `AnswerResponse` 装配合同 |
| `tests/contexts/identity/infrastructure/test_admin_user_repository.py` | +3 集成（新建，含并发） | `update_role` 原子替换唯一角色行与保留登录句柄、`list_paginated`、并发改角色唯一行实证 |
| `tests/contexts/identity/interfaces/test_admin_users_api.py` | +3 集成（新建，含并发） | 管理员端全权限/状态码矩阵、无 `password_hash` 泄漏、DB 实时角色切换旧 Token 立即生效、F07 悬赏仅教师守卫、并发改角色 |
| `tests/contexts/qa/infrastructure/test_verify_answer_repository.py` | +2 集成（新建） | `update_verification` 持久与还原、编辑/采纳保留认证态、条件 `UPDATE` 库级守卫（404/409） |
| `tests/contexts/qa/interfaces/test_verify_answer_api.py` | +2 集成（新建，含并发） | 认证/取消认证全状态矩阵、通知去重、零声誉变动、详情零 N+1、`asyncio.gather`（认证×关贴、认证×删答、5 教师并发重复认证） |
| `tests/test_contract.py` + `Fake*Repository` + `test_answer_vote_api.py` / `test_edit_answer_api.py` | 同步扩展 | `34 paths / 40 operations`、F15 schema 断言、7 处 `FakeAnswerRepository` 与 4 处 `FakeUserRepository` LSP 对齐 |

## 五、DoD 勾选

- [x] 六步法落地，仅触及 F15 范围，`test_architecture.py` 8 条 AST 护栏全绿
- [x] 迁移 `0c58c26e2c45` 已人工审核并在独立临时库 `campus_mig_test` 完成 `up → down → up → check` 往返；共享库已先备份至 D 盘再 `upgrade head` 零漂移
- [x] 单元 + 定向集成 + 并发 2 轮 + `v1.1.0` 全量真库集成回归实测通过（228 passed，F01–F15 零回归）
- [x] `openapi.json` 与 `tests/test_contract.py` 已同步且过 `--check`
- [x] 5 份文档（本台账、`docs/PROGRESS.md`、`docs/plan/f-engineering-standard.md`、`README.md`、`docs/api/api-contract-notes.md`）口径一致
- [x] 独立评测子代理（Auditor #1.2）5 维终审 + 真实 Uvicorn/Celery 冒烟 PASS（0 阻塞）
- [ ] 经用户批准推送 `feat/f15-rbac-and-verify` 提 PR 及 Actions 全绿，合入 `main` 后打 Tag `v1.1.0` 并更新 Wiki
