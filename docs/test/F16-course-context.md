# F16 重建 course 上下文与选课 · 开发与测试台账

> 日期：2026-11-25 · 上下文：`course`（依赖：`identity` 公开角色与展示名供给面） · 依赖：F08/F15（RBAC 4 角色）、F11（公开展示名 `UserSummaryReader`）
> 裁定：D1 上下文结构（新建 `app/contexts/course/{domain,application,infrastructure,interfaces}` 四层，严守 A1–A4 与 Zero Cross-Context FK）· D2 聚合与权限（`Course` 由 `teacher`/`admin` 创建，课程码去首尾空白并转大写，重复码 409；`Enrollment` `(course_id, student_id)` 复合唯一，限 `student` 自助选课，重复选课 409，课程不存在 404；`GET /api/v1/courses` 公开分页并支持 `semester` 筛选，`GET /api/v1/courses/{course_id}/students` 限 `teacher`/`ta`/`admin`，最小披露不含邮箱/学工号/密码哈希）· D3 已发布语言（`course/application/ports.py` 仅暴露 `CourseSummary` 与窄只读契约 `CourseAccessReader`，禁止暴露写/CRUD 方法）
> 分支/工作区：`feat/f16-course-context`（独立评测子代理 Auditor #2.1 终审 **PASS**，0 阻塞项）

## 一、交付范围

| 交付项 | 语义 |
|:--|:--|
| `GET /api/v1/courses` | **公开**分页查询课程列表；Query `page >= 1`（默认 1）、`page_size` 1..100（默认 20）、`semester` 可选（空白串视同无筛选，非空串经 `Semester` VO 校验，非法 422）；按 `(created_at DESC, id DESC)` 排序，`COUNT` 与列表复用单一 `_apply_filters`；响应 `{items, total, page, page_size, total_pages}`，批量用 `UserSummaryReader` 回填 `teacher_name` |
| `POST /api/v1/courses` | `require_roles("teacher", "admin")`（未登录 401，`student`/`ta` 403）；请求体 `CreateCourseRequest`（`extra="forbid"` + `str_strip_whitespace=True` + `reject_unsafe_text`）；`CourseCode` 单源归一化（`strip().upper()`，正则 `^[A-Z0-9][A-Z0-9_-]{1,31}$`）；重复课程码（含大小写变体）**409** `"课程编号已存在"`；成功 **201** + `CourseResponse` |
| `POST /api/v1/courses/{course_id}/enroll` | `require_roles("student")`（未登录 401，`teacher`/`ta`/`admin` 403）；先校验课程存在（缺失 **404** `"课程不存在"`），再落库选课记录（库级 `uq_enrollments_course_student` + `fk_enrollments_course_id` 兜底并发）；重复选课 **409** `"已选修该课程，请勿重复选课"`；成功 **201** + `EnrollmentResponse` |
| `GET /api/v1/courses/{course_id}/students` | `require_roles("teacher", "ta", "admin")`（未登录 401，`student` 403）；课程不存在 **404** `"课程不存在"`；按 `(enrolled_at ASC, id ASC)` 分页返回 `{items, total, page, page_size, total_pages}`；`CourseStudentItem` 最小披露仅含 `{student_id, student_name, enrolled_at}`（绝不含 `email`、学工号、`password_hash`），批量用 `UserSummaryReader` 回填 `student_name` |
| 已发布语言与迁移 | `course/application/ports.py` 暴露 `CourseSummary` 与 `CourseAccessReader`（`get_summary` / `get_summaries` 空集零 SQL / `is_enrolled`），`course/interfaces/api/deps.py` 导出 `CourseAccessReaderDep` 供 F17 消费；迁移 `965519fef7b7` 新增 `courses` 与 `enrollments` 表及唯一/查询索引（零跨上下文外键） |

明确不做（Non-Goals）：修改 `questions` 表与 `app/contexts/qa/`（留给 F17）；退课/删课/改课端点；课程公告或课程资源；前端页面修改。

## 二、六步法改动清单

| 步骤 | 文件 | 改动 |
|:--|:--|:--|
| 1 domain | `app/contexts/course/domain/errors.py`、`value_objects.py`、`course.py`、`enrollment.py`、`repository.py` | 定义 `CourseDomainError` 异常族、`CourseCode`/`CourseName`/`Semester` 值对象（`DomainValidationError` + `reject_unsafe_text`）、`Course`/`Enrollment` 聚合与 `CourseRepository`/`EnrollmentRepository` 端口 |
| 2 application | `app/contexts/course/application/ports.py`、`commands.py`、`queries.py`、`create_course_use_case.py`、`list_courses_use_case.py`、`enroll_course_use_case.py`、`list_course_students_use_case.py` | 定义窄只读已发布语言 `CourseSummary`/`CourseAccessReader`、命令/查询 DTO（`total_pages` 同 `identity` 口径）与 4 个独立单责用例 |
| 3 infrastructure | `app/contexts/course/infrastructure/models.py`、`course_repository.py`、`enrollment_repository.py`、`course_access_reader.py`；`alembic/env.py`；`alembic/versions/965519fef7b7_add_courses_and_enrollments_tables.py` | 声明 `courses`/`enrollments` 模型（零跨上下文 FK）、实现 PG 仓储（单源 `_apply_filters`、SQLSTATE `23505`/`23503` 精准转译且禁透传 `str(exc.orig)`）与 `SqlAlchemyCourseAccessReader`（空集零 SQL）；生成并审核迁移 `965519fef7b7` |
| 4 interfaces | `app/contexts/course/interfaces/api/schemas.py`、`error_mapping.py`、`deps.py`、`routes.py`；`app/main.py` | 定义请求/响应 Schema、`COURSE_ERROR_STATUS` 映射、`AuthenticatedUser(Protocol)` 守 A4、角色依赖与 `CourseAccessReaderDep`、4 个薄壳路由并挂载至 `create_app()` |
| 5 tests | `tests/contexts/course/{domain,application,infrastructure,interfaces}/`、`tests/test_contract.py` | 新增 domain 40 单测、application 7 单测（LSP Fake 仓储）、interfaces 7 单测、仓储集成 1、API 全权限矩阵与并发集成 2（含 6 并发创建同课码与 6 并发重复选课）；`test_contract.py` 更新至 `37 paths / 44 operations` 与 F16 schema 断言 |
| 6 收口 | `openapi.json`、本台账、`docs/PROGRESS.md`、`docs/plan/f-engineering-standard.md`、`README.md`、`docs/api/api-contract-notes.md` | 重导出契约过 `--check`，同步 5 份文档与四级门禁真实自测结果 |

### 关键设计与人工审核记录
- **迁移人工审核**：`alembic revision --autogenerate -m "add courses and enrollments tables"` 精确检出 `courses`（`uq_courses_code`、`ix_courses_semester`、`ix_courses_teacher_id`）与 `enrollments`（`fk_enrollments_course_id` `ON DELETE CASCADE`、`uq_enrollments_course_student`、`ix_enrollments_course_id`、`ix_enrollments_student_id`），无多余列或索引漂移；`downgrade()` 先删 `enrollments` 索引与表再删 `courses` 索引与表。
- **并发与信息安全**：`CourseCode` 单源将 `" cs-se-301 "` 归并为 `"CS-SE-301"`，`uq_courses_code` 与 `uq_enrollments_course_student` 为并发写入提供库级唯一兜底；仓储异常翻译根据 `pgcode`/`constraint_name` 映射 `CourseCodeAlreadyExistsError`/`AlreadyEnrolledError`/`CourseNotFoundError`，绝不将 `str(exc.orig)` 暴露给客户端。
- **包边界（A4）**：`course/interfaces/api/deps.py` 不直接 import `identity.domain`，定义本地 `AuthenticatedUser(Protocol)` 承接 `require_roles(...)` 返回对象，通过 `mypy --strict` 与 `test_architecture.py` 8 条护栏。

## 三、门禁与实测证据（2026-11-25）

| 检查项 | 命令 | 结果 |
|:--|:--|:--|
| Lint | `.venv\Scripts\ruff.exe check .` | `All checks passed!`（0 违规） |
| 严格类型检查 | `.venv\Scripts\mypy.exe app` | `Success: no issues found in 171 source files` |
| 契约导出与防漂移 | `.venv\Scripts\python.exe scripts/export_openapi.py --check` | `openapi.json 与当前代码一致`（**37 paths / 44 operations**） |
| 架构 + 契约测试 | `.venv\Scripts\pytest.exe tests/test_architecture.py tests/test_contract.py -q` | **18 passed**（4.74s，8 条 AST 护栏 0 违规） |
| CI 单元回归 + 覆盖率 | `.venv\Scripts\pytest.exe -m "not integration" --cov=app --cov-report=term-missing --cov-fail-under=70 -q` | **462 passed**, 231 deselected（16.53s）；TOTAL **83.41%** |
| 核心聚合覆盖率 | `.venv\Scripts\python.exe -m coverage report --include="*/domain/*" --fail-under=90` | **94%**（`course/domain/{course,enrollment,errors,value_objects}.py` 均 **100%**） |
| 隔离库迁移往返 | 独立临时库 `campus_mig_test` 执行 `f16_mig_roundtrip.py`（`upgrade head → downgrade -1 → upgrade head → check` + 库对象检查 + `DROP DATABASE`） | `965519fef7b7 (head)` → `0c58c26e2c45` → `965519fef7b7 (head)`；`No new upgrade operations detected.`；临时库已销毁 |
| 共享库备份与升级 | `docker exec campusoverflow-db-1 pg_dump -U campus campus > D:\a_work\_archive\db_backups\campus_pre_f16.sql`；`alembic upgrade head` / `current` / `check` | 备份 **9,920,502 B**（D 盘）；共享库平滑升至 `965519fef7b7 (head)`，`No new upgrade operations detected.` |
| F16 定向集成 + 并发 2 轮 | `pytest tests/contexts/course/infrastructure/test_course_repository.py tests/contexts/course/interfaces/test_course_api.py -v`（连续 2 轮） | 第 1 轮 **3 passed**（12.47s）/ 第 2 轮 **3 passed**（12.28s）；Auditor 复核 **3 passed × 2**（13.85s / 13.90s） |
| 跨模块关联回归 | `test_admin_users_api.py`、`test_verify_answer_api.py`、`test_f11_display_name_and_profile_api.py`、`test_question_api.py` | **50 passed**（90.01s；Auditor 复核 **50 passed**，92.27s） |
| 真实进程端到端冒烟 | 真实 `uvicorn app.main:app`（`127.0.0.1:18126` / Auditor 独立复核 `127.0.0.1:18127`）连真实 PG `15432` + Redis `16379` | Builder **28 HTTP 请求全绿** + Auditor **49 HTTP 请求全绿**（含主干提问/回答/投票回归 + F16 全正反向路径与最小披露核验），日志 0 HTTP 500 / 0 未捕获 Traceback，测试数据 0 残留 |

### 测试数据知识来源（遵循真实知识测试数据规范）
- 课程《软件工程》（CS-SE-301）、《操作系统》（CS-OS-201，参考 OSTEP `https://pages.cs.wisc.edu/~remzi/OSTEP/`）、《数据库系统原理》（CS-DB-202，参考 PostgreSQL 文档 `https://www.postgresql.org/docs/current/`）。

## 四、测试覆盖

| 文件 | 改动 | 覆盖点 |
|:--|:--|:--|
| `tests/contexts/course/domain/test_course_domain.py` | +40 单测（新建） | `CourseCode` 归一化/格式、`CourseName`/`Semester` 长度与控制字符/lone surrogate 拒收、`Course.create` / `Enrollment.enroll` |
| `tests/contexts/course/application/test_course_use_cases.py` | +7 单测（新建） | `CreateCourseUseCase` / `ListCoursesUseCase` / `EnrollCourseUseCase` / `ListCourseStudentsUseCase` 及 LSP Fake 仓储 |
| `tests/contexts/course/interfaces/test_course_routes_unit.py` | +7 单测（新建） | 四路由 RBAC 门禁矩阵、`extra=forbid`/422/404/409 状态码、最小披露白名单 |
| `tests/contexts/course/infrastructure/test_course_repository.py` | +1 集成（新建） | PG 仓储、`23505`/`23503` 异常翻译禁泄露 `exc.orig`、`COUNT` 对账、`CourseAccessReader.get_summaries([])` 零 SQL 实证 |
| `tests/contexts/course/interfaces/test_course_api.py` | +2 集成（新建，含并发） | 真实 PG+Redis 下全角色权限矩阵、分页 `total` 对账、大小写归并 409、最小披露、`asyncio.gather` 6 并发创建与 6 并发选课 |
| `tests/test_contract.py` | 同步扩展 | `_FAMILIES` 加入 `"courses"`，更新计数为 `37 paths / 44 operations`，新增 F16 schema 断言 |

## 五、DoD 勾选

- [x] 六步法落地，仅触及 F16 范围，`test_architecture.py` 8 条 AST 护栏全绿
- [x] 迁移 `965519fef7b7` 已人工审核并在独立临时库 `campus_mig_test` 完成 `up → down → up → check` 往返；共享库已先备份至 D 盘再 `upgrade head` 零漂移
- [x] 单元 + 定向集成 + 并发 2 轮 + 跨模块关联回归 + 真实 Uvicorn 冒烟实测通过
- [x] `openapi.json` 与 `tests/test_contract.py` 已同步且过 `--check`
- [x] 5 份文档（本台账、`docs/PROGRESS.md`、`docs/plan/f-engineering-standard.md`、`README.md`、`docs/api/api-contract-notes.md`）口径一致
- [x] 独立评测子代理终审 PASS（Auditor #2.1：`PASS`，0 阻塞项）
- [ ] 经用户批准提交推送 `feat/f16-course-context`、提 PR 及远端 CI 全绿后合入 `main`
