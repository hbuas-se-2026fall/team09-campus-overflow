# F17 问题关联课程与课程筛选/榜单 · 开发与测试台账

> 日期：2026-11-25 · 上下文：`qa`（消费 `course` 已发布语言 `CourseAccessReader`） · 依赖：F01（问题筛选）、F05（排名口径）、F11（公开展示名）、F13（软删除过滤）、F16（课程与选课）
> 裁定：D1 校验位置（`qa/application/ports.py` 定义窄 `CourseAccessReader` 端口，单源准入策略 `course_access_policy.py` 在 `AskQuestionUseCase` 与 `EditQuestionUseCase` 处执行，路由零业务逻辑，`qa/interfaces/api/deps.py` 通过 `_CourseAccessAdapter` 适配 `course` 端口，严守 A4/DIP/SRP）· D2 发问准入与存储（`questions.course_id` 可空 UUID，零跨上下文外键，存量 `NULL`；学生发问/改绑必须已选修该课程，未选 403、缺课 404；`teacher`/`ta`/`admin` 允许跨课关联；`PATCH` 传 `course_id: null` 解绑、缺省保留）· D3 课程筛选与课程榜单（`QuestionFilter.course_id` 复用 `_apply_filters` 单一谓词源；列表/详情/相关问题批量 `IN` 回填 `course_name`；`GET /api/v1/courses/{course_id}/leaderboard` 落 `qa` 只读聚合，先按回答粒度算净赞再按作者聚合，杜绝多票乘倍，严格剔除软删，零写入 `reputation_ledgers`，守住 A5）
> 分支/工作区：`feat/f17-question-course`（独立评测子代理 Auditor #2.2 终审 **PASS**，0 阻塞项）

## 一、交付范围

| 交付项 | 语义 |
|:--|:--|
| `POST /api/v1/questions`（增量扩展） | 请求体 `AskQuestionRequest` 新增可选 `course_id: UUID | null`；不传/`null` 100% 向后兼容且零额外课程 SQL；传 `course_id` 时应用层校验课程存在（404 `"课程不存在"`）及学生选课准入（未选修 403 `"仅已选修该课程的学生可在该课程下提问"`；`teacher`/`ta`/`admin` 跨课放行）；`QuestionResponse` 增量返回 `course_id` 与 `course_name` |
| `PATCH /api/v1/questions/{question_id}`（增量扩展） | 请求体 `EditQuestionRequest` 新增可选 `course_id: UUID | null`（允许仅传 `{"course_id": null}` 解绑课程；空 `{}` 422）；锁问题后先校验存在(404)/作者(403)/未关闭(409)，仅当 `course_id` 在 `model_fields_set` 且非 `null` 时走单源课程准入校验（404/403），缺省时保留原 `course_id` |
| `GET /api/v1/questions`、`/{id}`、`/{id}/related`（增量扩展） | 列表新增 Query 参数 `course_id: UUID | null`，纳入 `_apply_filters` 与 `COUNT` 同口径筛选，可与 `tag`/`status`/`q`/`created_from/to`/`sort` 组合；列表/相关问题通过单次 `get_summaries` `IN` 查询批量回填 `course_name`（无课程题零 SQL），详情同步返回 `course_id`/`course_name` |
| `GET /api/v1/courses/{course_id}/leaderboard` | **公开**课程贡献榜单，Query `limit` 1..50（默认 20）；课程不存在 **404**；基于该课程下未软删除问题关联的未软删除回答聚合 `accepted_count`、`net_votes`、`answer_count` 及 `RANK() OVER (ORDER BY accepted_count DESC, net_votes DESC)`，按 `(accepted_count DESC, net_votes DESC, answer_count DESC, author_id ASC)` 排序并实时回填 F11 `display_name`；空课返回 `200` + `entries: []`；**零写入 `reputation_ledgers`** |
| 数据库迁移 | 迁移 `13a011cb2db6`：`questions` 表新增可空 `course_id`（`UUID`）与索引 `ix_questions_course_id`，零跨上下文外键，存量问题自动保持 `NULL` |

明确不做（Non-Goals）：标签分类（旧 F18 已搁置）；修改 `reputation_ledgers` 与全站 `GET /api/v1/leaderboard`；课程删除/退课级联；前端页面修改。

## 二、六步法改动清单

| 步骤 | 文件 | 改动 |
|:--|:--|:--|
| 1 domain | `app/contexts/qa/domain/errors.py`、`question.py`、`repository.py` | 新增 `CourseNotFoundError` / `CourseEnrollmentRequiredError`；`Question` 与 `ask` / `edit_title_body` 支持 `course_id` 与 `UNSET`；`QuestionFilter` 增 `course_id`，新增 `CourseLeaderboardEntry` 与 `CourseLeaderboardRepository` Protocol |
| 2 application | `app/contexts/qa/application/ports.py`、`course_access_policy.py`（新建）、`commands.py`、`queries.py`、`ask_question_use_case.py`、`edit_question_use_case.py`、`get_course_leaderboard_use_case.py`（新建） | 定义 `CourseSummary` / `CourseAccessReader` 窄端口（零 `import course`）、单源 `ensure_course_question_access` 策略、扩展提问/编辑命令与用例、新增 `GetCourseLeaderboardUseCase` |
| 3 infrastructure | `app/contexts/qa/infrastructure/models.py`、`question_repository.py`、`course_leaderboard_repository.py`（新建）；`alembic/versions/13a011cb2db6_add_question_course_id_column_f17.py`（新建） | `QuestionModel` 增 `course_id` + `ix_questions_course_id`；`SqlAlchemyQuestionRepository` 读写与 `_apply_filters` 同步 `course_id`；新建 `SqlAlchemyCourseLeaderboardRepository`（回答子查询防票数膨胀）；生成并审核迁移 `13a011cb2db6` |
| 4 interfaces | `app/contexts/qa/interfaces/api/error_mapping.py`、`deps.py`、`schemas.py`、`questions.py`、`course_leaderboard.py`（新建）、`routes.py`；`app/main.py` | 注册 404/403 映射；新增 `_CourseAccessAdapter` 与依赖；响应增量暴露 `course_id`/`course_name` 并批量回填（无课程零 SQL）；挂载 `GET /api/v1/courses/{course_id}/leaderboard` |
| 5 tests | `tests/contexts/qa/{domain,application,infrastructure,interfaces}/`、`tests/test_contract.py` | 更新 `test_question.py`、`test_question_filter.py`、`test_question_api.py`（3 处键集合）；新建 `test_question_course_use_cases.py`、`test_question_course_routes_unit.py`、`test_course_leaderboard_repository.py`、`test_question_course_api.py`（含并发实证）；契约测试升至 `38 paths / 45 operations` |
| 6 收口 | `openapi.json`、本台账、`docs/PROGRESS.md`、`docs/plan/f-engineering-standard.md`、`README.md`、`docs/api/api-contract-notes.md` | 重导出契约过 `--check`，同步 5 份文档与四级门禁真实自测结果 |

### 关键设计与人工审核记录
- **迁移人工审核**：`alembic revision --autogenerate -m "add question course_id column f17"` 仅检出 `questions.course_id`（`nullable=True`）与 `ix_questions_course_id`（零多余列/索引漂移）；`downgrade()` 先删 `ix_questions_course_id` 再删列 `course_id`。
- **防票数膨胀与软删除过滤**：`SqlAlchemyCourseLeaderboardRepository` 先构造按 `AnswerModel.id` 粒度的 `per_answer` 子查询（复用 `net_votes_expr()` 标量子查询并过滤 `QuestionModel.deleted_at.is_(None)` 与 `AnswerModel.deleted_at.is_(None)`），再在外部按 `author_id` 聚合 `accepted_count`、`net_votes`、`answer_count` 与 `RANK()`，从 SQL 结构上杜绝多张投票放大 `answer_count` / `accepted_count`。

## 三、门禁与实测证据（2026-11-25）

| 检查项 | 命令 | 结果 |
|:--|:--|:--|
| Lint | `.venv\Scripts\ruff.exe check .` | `All checks passed!`（0 违规） |
| 严格类型检查 | `.venv\Scripts\mypy.exe app` | `Success: no issues found in 175 source files` |
| 契约导出与防漂移 | `.venv\Scripts\python.exe scripts/export_openapi.py --check` | `openapi.json 与当前代码一致`（**38 paths / 45 operations**） |
| 架构 + 契约测试 | `.venv\Scripts\pytest.exe tests/test_architecture.py tests/test_contract.py -q` | **19 passed**（4.76s，8 条 AST 护栏 0 违规） |
| CI 单元回归 + 覆盖率 | `.venv\Scripts\pytest.exe -m "not integration" --cov=app --cov-report=term-missing --cov-fail-under=70 -q` | **470 passed**, 234 deselected（17.46s）；TOTAL **84.15%** |
| 核心聚合覆盖率 | `.venv\Scripts\python.exe -m coverage report --include="*/domain/*" --fail-under=90` | **94%**（`qa/domain/{question,errors}.py` 均 **100%**） |
| 隔离库迁移往返 | 独立临时库 `campus_mig_test` 执行 `f17_mig_roundtrip.py`（`upgrade head → downgrade -1 → upgrade head → check` + 库对象检查 + `DROP DATABASE`） | `13a011cb2db6 (head)` → `965519fef7b7` → `13a011cb2db6 (head)`；`No new upgrade operations detected.`；临时库已销毁 |
| 共享库备份与升级 | `docker exec campusoverflow-db-1 pg_dump -U campus campus > D:\a_work\_archive\db_backups\campus_pre_f17.sql`；`alembic upgrade head` / `current` / `check` | 备份 **10,087,690 B**（D 盘）；共享库平滑升至 `13a011cb2db6 (head)`，`No new upgrade operations detected.` |
| F17 定向集成 + 并发 2 轮 | `pytest tests/contexts/qa/infrastructure/test_course_leaderboard_repository.py tests/contexts/qa/interfaces/test_question_course_api.py -v`（连续 2 轮） | 第 1 轮 **3 passed**（15.15s）/ 第 2 轮 **3 passed**（15.49s）；Auditor 复核 **3 passed × 2**（21.61s / 21.05s） |
| 跨模块关联回归 | `test_course_api.py`、`test_soft_delete_api.py`、`test_leaderboard_api.py`、`test_question_api.py`、`test_close_edit_api.py`、`test_verify_answer_api.py` | **71 passed**（154.55s；Auditor 复核 **71 passed**，174.07s） |
| 真实进程端到端冒烟 | 真实 `uvicorn app.main:app`（`127.0.0.1:18127` / Auditor 独立复核 `127.0.0.1:18128`）连真实 PG `15432` + Redis `16379` | Builder **27 HTTP 请求全绿** + Auditor **54 HTTP 请求全绿**（含 F17 全正反向路径与主干回归），日志 0 HTTP 500 / 0 未捕获 Traceback，测试数据 0 残留 |

### 测试数据知识来源（遵循真实知识测试数据规范）
- 软件工程（CS-SE-301）依赖倒置与六边形架构；数据库系统原理（CS-DB-202，PostgreSQL MVCC 与 B+ 树索引 `https://www.postgresql.org/docs/current/mvcc.html`）；操作系统（CS-OS-201，Clock 页面置换 `https://pages.cs.wisc.edu/~remzi/OSTEP/`）。

## 四、测试覆盖

| 文件 | 改动 | 覆盖点 |
|:--|:--|:--|
| `tests/contexts/qa/domain/test_question.py` | +1 综合单测 | `Question.ask` / `edit_title_body` 的 `course_id`、`UNSET` 保留、`None` 解绑与失败无半改 |
| `tests/contexts/qa/domain/test_question_filter.py` | +1 单测 | `QuestionFilter.course_id` 筛选字段保留与默认 `None` |
| `tests/contexts/qa/application/test_question_course_use_cases.py` | +4 单测（新建） | 提问/编辑全角色课程准入矩阵（403/404/409/200/201）、`GetCourseLeaderboardUseCase` 与 `limit` 越界校验 |
| `tests/contexts/qa/interfaces/test_question_course_routes_unit.py` | +1 综合单测（新建） | 无 `course_id` 零查库、403/404/422、编辑 `course_id: null` 解绑、列表/详情/相关问题回填、课程榜单路由 |
| `tests/contexts/qa/infrastructure/test_course_leaderboard_repository.py` | +1 集成（新建） | `QuestionRepository` `course_id` 筛选；课程榜单多票不膨胀、软删剔除、`RANK()` 同分同名次（1,1,3）与 `reputation_ledgers` 零写入 |
| `tests/contexts/qa/interfaces/test_question_course_api.py` | +2 集成（新建，含并发） | 真实 PG+Redis 全角色权限矩阵、`course_id` 组合筛选 + 批量 `IN` 回填（1 次 `FROM courses` 查询）、榜单与 `asyncio.gather` 并发实证 |
| `tests/contexts/qa/interfaces/test_question_api.py` & `tests/test_contract.py` | 同步键集合与契约断言 | 3 处 `set(keys)` 增 `course_id`/`course_name`；`test_contract.py` 升至 `38 paths / 45 operations` 与 F17 schema 断言 |

## 五、DoD 勾选

- [x] 六步法落地，仅触及 F17 范围，`test_architecture.py` 8 条 AST 护栏全绿（`reputation` 对 `qa` 零耦合）
- [x] 迁移 `13a011cb2db6` 已人工审核并在独立临时库 `campus_mig_test` 完成 `up → down → up → check` 往返；共享库已先备份至 D 盘再 `upgrade head` 零漂移
- [x] 单元 + 定向集成 + 并发 2 轮 + 跨模块关联回归 + 真实 Uvicorn 冒烟实测通过
- [x] `openapi.json` 与 `tests/test_contract.py` 已同步且过 `--check`
- [x] 5 份文档（本台账、`docs/PROGRESS.md`、`docs/plan/f-engineering-standard.md`、`README.md`、`docs/api/api-contract-notes.md`）口径一致
- [x] 独立评测子代理终审 PASS（Auditor #2.2：`PASS`，0 阻塞项）
- [ ] 经用户批准提交推送 `feat/f17-question-course`、提 PR 及远端 CI 全绿后合入 `main`
