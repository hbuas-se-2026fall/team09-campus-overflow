# F11 公开展示名供给面与个人主页 · 开发与测试台账

> 日期：2026-11-18 · 上下文：`identity`（供给面 + 主页端点）+ `qa` / `reputation` / `discovery`（仅 `interfaces/api` 层回填）· 依赖：F08 榜单缓存、F09 单 SQL 读路径、F10 校园资料扩展
> 裁定：D1 `resolve_display_name(role, user_id, nickname: str | None)` 单源规则（`strip()` 非空优先，空/None 按 `_ROLE_DISPLAY_PREFIXES` 回退 `学生#<8位hex>`/`教师#<8位hex>`，未知角色回退通用 `用户#<8位hex>`，禁泄露学工号/邮箱）· D2 `UserSummary`/`PublicUserProfile`/`UserSummaryReader`/`PublicUserProfileReader` 与单源缺失兜底 `pick_summary_display_name` 全部归 `identity/application/ports.py`，下游仅在 `interfaces/api` 层回填（守 A1–A5）· D3 榜单缓存仍只存 `(user_id, score, rank)`，路由层实时回填 `display_name` · D4 独立只读用例 + 显式列投影实现 `GET /api/v1/users/{user_id}/profile`，顶层字段用 `user_id`，去掉 `created_at` 与全部隐私列 · D5 批量与主页 reader 用 `.all()` + 固定角色优先级（`teacher` > `student`）去重并记 warning，缺失用户安全回退 `"未知用户"`，不抛 500
> 分支/工作区：`feat/f11-display-name-and-profile`

## 一、交付范围

| 交付项 | 语义 |
|:--|:--|
| `UserSummaryReaderDep`（跨上下文公开供给面） | 批量 `WHERE users.id IN (...)` 单次查询返回 `dict[UUID, UserSummary]`；空集合发 0 SQL；缺失 ID 不入字典不报错；多角色脏数据按固定优先级收敛并记 warning |
| `qa` 响应增量回填 `author_name` | `QuestionResponse`、`QuestionListItem`、`QuestionDetailResponse`、`AnswerResponse`、`CommentResponse` 增 `author_name`；写接口直接取 `user.display_name`（0 额外 SQL）；列表/相关/详情合并去重后仅 1 次批量查询 |
| `reputation` 榜单回填 `display_name` | `LeaderboardEntryResponse` 增 `display_name`；即使命中 60s Redis 缓存仍实时回填，改昵称立即生效 |
| `discovery` 通知回填 `actor_name` | `NotificationResponse` 增 `actor_name`；单次批量查询回填 |
| `GET /api/v1/users/{user_id}/profile` | 公开访客可用；用户不存在 404（`"用户不存在"`）；最小披露返回 `{user_id, role, display_name, nickname, college, class_name}`，不含 `email`/`student_id`/`staff_id`/`email_verified`/`password_hash`/`created_at` |

明确不做：新建 Alembic 迁移（复用 F10）、改动 `BountyResponse`/`UserBadgesResponse`/`RegisterResponse`、在 `/profile` 聚合徽章/声誉/发帖、前端 UI 页面、用户摘要 Redis 缓存。

## 二、六步法改动清单

| 步骤 | 文件 | 改动 |
|:--|:--|:--|
| 1 domain | `app/contexts/identity/domain/user.py` | 新增 `normalize_public_nickname`、`resolve_display_name` 与 `User.display_name` 只读属性 |
| 2 application | `app/contexts/identity/application/ports.py`、`get_public_profile_use_case.py` | 新增已发布语言 `UserSummary`/`PublicUserProfile`/`UserSummaryReader`/`PublicUserProfileReader` 与 `GetPublicUserProfileUseCase` |
| 3 infrastructure | `app/contexts/identity/infrastructure/user_summary_reader.py` | 实现 `SqlAlchemyUserSummaryReader`（显式列投影、不连 `students`/`teachers`、固定角色优先级 `_ROLE_PRIORITY` + warning、清洗 `nickname`、无需迁移） |
| 4 interfaces | `identity` `deps.py`/`schemas.py`/`routes.py`、`app/main.py`；`qa` `schemas.py`/`_common.py`/`questions.py`/`answers.py`；`reputation` `schemas.py`/`routes.py`；`discovery` `schemas.py`/`routes.py` | 暴露 `UserSummaryReaderDep`/`PublicUserProfileReaderDep`；新增 `users_router` 与 `/profile`；下游 `interfaces/api` 批量回填展示名 |
| 5 tests | 领域/用例/读模型/接口单测 + 4 条 F11 集成测试 + 3 处既有 key-set 断言同步 | 单测 +14、集成 +4，全库运行 `330 passed / 194 passed = 524 passed` |
| 6 收口 | `openapi.json`、`tests/test_contract.py`、本台账、`docs/api/api-contract-notes.md`、`docs/PROGRESS.md`、`README.md` | 契约升至 `30 paths / 33 ops`，文档与门禁全数登记 |

### 关键设计

- **跨上下文零循环依赖**：已发布语言只包含基础类型（`UUID`/`str`）并收口在 `identity/application/ports.py`，下游只在 `interfaces/api` 注入 `UserSummaryReaderDep`，`domain`/`application` 对 `identity` 零耦合（A1–A5 全过）。
- **多角色与脏昵称兜底**：读模型使用 `_ROLE_PRIORITY = {"teacher": 0, "student": 1}` 确定性收敛（不依赖字母序变化；若 F15 引入 `ta`/`admin`，须同步裁定其优先级），`get_public_profile` 复用 `normalize_public_nickname` 确保 `nickname` 与 `display_name` 始终一致。
- **详情页防 N+1**：`get_question` 将题主、全部回答、全部题评与答评的 `author_id` 合并去重，经单次 `get_summaries()` 批量查询回填。

## 三、门禁实测（2026-11-18）

| 门禁 | 命令 | 结果 |
|:--|:--|:--|
| Lint | `ruff check .` | `All checks passed!` |
| 类型 | `mypy app` | `Success: no issues found in 143 source files` |
| 单元 + 总覆盖率 | `pytest -m "not integration" --cov=app --cov-report=term-missing --cov-fail-under=70 -q` | **330 passed**, 194 deselected；TOTAL **83.60%** |
| 核心聚合覆盖率 | `python -m coverage report --include="*/domain/*" --fail-under=90` | **94%**（`identity/domain/user.py` 100%） |
| 契约防漂移 | `python scripts/export_openapi.py --check` | `openapi.json 与当前代码一致`（**30 paths / 33 operations**） |
| 架构 + 契约测试 | `pytest tests/test_architecture.py tests/test_contract.py -v` | **15 passed** |
| 全量集成 | `pytest -m integration -q` | **194 passed**, 330 deselected（275.41s，最终版代码全量通过） |
| 迁移状态 | `alembic current` & `alembic check` | `c451483b0660 (head)`；`No new upgrade operations detected.`（无新增迁移） |

## 四、测试覆盖

| 文件 | 条数 | 覆盖点 |
|:--|:--|:--|
| `tests/contexts/identity/domain/test_user.py` | +6 | `resolve_display_name` 清洗/空串与空白回退、`学生#<8hex>`/`教师#<8hex>`、`User.display_name` 不含学工号/邮箱 |
| `tests/contexts/identity/application/test_get_public_profile_use_case.py` | 2（新建） | 存在返回公开档案、不存在返回 `None` |
| `tests/contexts/identity/infrastructure/test_user_summary_role_resolution.py` | 4（新建） | 无角色回退 `student`、多角色固定优先级 `teacher` + warning 日志、未知角色排序、`display_name_for` 缺失兜底 `"未知用户"` |
| `tests/contexts/identity/interfaces/test_public_profile_api_unit.py` | 2（新建） | `/profile` 200/404 依赖覆盖单测；列表/榜单/通知缺失用户回退 `"未知用户"` |
| `tests/contexts/identity/interfaces/test_f11_display_name_and_profile_api.py` | 4（新建集成） | 空输入 0 SQL & 批量去重恰好 1 SQL；多角色脏数据 + 脏空白昵称不 500 且清洗一致；`/profile` 有/无昵称与教师态及 404 与隐私字段负向断言；`qa` 写路径 0 额外 SQL / 读路径恰好 1 SQL + 改昵称实时回填；`reputation` 缓存命中下改昵称实时回填 + `discovery` 通知实时回填 |
| `test_question_api.py` / `test_accept_comment_api.py` / `test_answer_vote_api.py` / `test_contract.py` | 同步 | 补全 `author_name` 字段断言与 `30 paths / 33 ops` |

## 五、DoD 勾选

- [x] 六步法落地，`test_architecture.py` 全绿（A1–A8 零违规）
- [x] 无需新增迁移，`alembic check` 零漂移
- [x] 单元（+14）与真实 PG+Redis 集成（+4）实测全绿（总 524 passed）
- [x] `openapi.json`（30 paths / 33 ops）与 `tests/test_contract.py` 已同步且过 `--check`
- [x] 本台账、`docs/api/api-contract-notes.md`、`docs/PROGRESS.md`、`README.md` 已登记
- [x] 本地六道门禁 + 架构/契约测试全绿
