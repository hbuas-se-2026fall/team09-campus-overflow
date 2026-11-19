# CampusOverflow — Claude Code 首提示词

> 用法：新建空目录 → `cd` 进去 → `git init` → 启动 `claude` → 把下面「首提示词」整段粘贴进去（一次性发出，不要拆）。
> 目标状态 = 本仓库现在的程度：**阶段 0–3 全部收口，阶段 4（上线）明确不做**。

---

## 首提示词（整段复制）

```
你是我的结对工程师，我负责验收，你负责实现。现在这个目录是空的，请从零搭建
"校园问答知识社区" CampusOverflow，做到「阶段 0–3 完成、阶段 4 不启动」的状态。

═══ 一、铁律（违反任何一条即视为任务失败） ═══
1. 课程要求：不参考、不复制任何开源项目代码。设计只能来自我给的规格和你的推理，
   不许去 GitHub 找同类项目抄结构。
2. 任何"完成/通过"的结论必须有刚跑过的命令输出作证。禁止编造测试结果、覆盖率、
   CI 状态。没跑过就写"未验证"。
3. 遇到阻塞（缺 Docker、缺 PostgreSQL、缺账号、网络不通）立刻停下来告诉我缺什么、
   影响哪一步，不要绕过去假装做完。
4. 一次只推进一个阶段；每个阶段结束必须停下来等我确认，不许一口气跑到底。
5. 依赖纪律：技术栈以下面清单为准，不许擅自换框架/加新库。确实需要新依赖时，
   先说明理由等我点头。
6. 不许为了让门禁通过而降低标准（改阈值、加 noqa、删测试、把 mypy 改成非 strict）。
7. 所有代码注释、文档、提交信息用中文；代码标识符用英文。

═══ 二、产品与范围 ═══
定位：面向高校的问答知识社区，学生按课程/标签提问答疑，讨论沉淀为教学资产，
声誉体系量化学习参与度。
角色：访客（只读）、学生（学号注册）、教师（工号注册）。
核心用例：注册/登录/刷新令牌、发问题（≤5 标签）、问题列表（分页+排序）、
问题详情（答案按采纳优先、三级评论）、编辑/关闭问题、回答、问题和回答投票、
问题评论+回答评论、采纳最佳答案、标签目录、声誉查询、健康探针。
明确不做（阶段 4 之前）：搜索推荐、通知推送、课程管理、文件上传、管理后台。

═══ 三、技术栈（不得替换） ═══
Python 3.12+；FastAPI + Uvicorn；SQLAlchemy 2.0 async + Alembic；PostgreSQL 16；
Redis 7（db0 存 Refresh 令牌、db1 作 Celery broker）；Pydantic v2；Celery（声誉异步记账）；
pytest + pytest-asyncio + httpx；ruff（line-length 100，select E/F/I/UP/B）+ mypy --strict；
GitHub Actions；Docker Compose；前端 React 18 + TS 5 + Vite + Ant Design + React Query + Zustand。

═══ 四、架构（DDD 限界上下文纵切，单体模块化） ═══
app/
├── config/settings.py        Pydantic Settings，.env 覆盖，字段都有开发默认值
├── shared/                   引擎、异常基类与处理器、文本校验等共享内核
└── contexts/
    ├── identity/{domain,application,infrastructure,interfaces}
    ├── qa/{domain,application,infrastructure,interfaces}
    ├── reputation/{domain,application,infrastructure,interfaces}
    ├── course/       （只建骨架，不实现）
    └── discovery/    （只建骨架，不实现）
alembic/   tests/   docs/   frontend/   scripts/   docker-compose.yml

硬约束：
- domain 层是纯 Python，禁止 import fastapi / sqlalchemy / pydantic。
- 聚合刻意收小：Question 聚合只含 Question + Vote；跨聚合协作走应用层编排 + 领域事件。
- reputation 上下文对 qa 零 import，只通过事件载荷通信。
- 主键统一 UUID；仓储以端口（Protocol/抽象基类）+ 基础设施实现，依赖注入组装。
- 路由与依赖统一 Depends(get_session, scope="function")，保证提交先于响应发送。

═══ 五、业务规则（写进领域层，不许只写在路由里） ═══
- 口令 bcrypt 哈希；学号/工号 + 邮箱唯一；重复注册 409。
- JWT：Access 15 分钟、Refresh 7 天存 Redis；刷新用 GETDEL 原子轮换，旧令牌失效；
  登出吊销 Refresh，幂等 204。
- 登录失败 5 次 / 15 分钟窗口 → 423；计数对学号与工号统一，防枚举。
- 投票：复合唯一索引 (user_id, target_type, target_id)；重复票/改票一律 409；自投不计分。
- 采纳：仅提问者，非作者 403，重复采纳 409；部分唯一索引保证"一题一采纳"。
- 关闭问题为终态：投票/新增回答/评论/采纳/编辑全部 409，用条件 UPDATE 做库级兜底。
- 声誉规则：回答被赞 +10、回答被踩 -2、问题被赞 +5、问题被踩 -2、回答被采纳 +15；
  流水表唯一索引 (source, event_id) 保证幂等；Celery task_acks_late=True 至少一次投递；
  Windows 下 worker 必须 --pool=solo。
- 连接池：db_pool_size=0 走 NullPool（测试/CI 零影响），>0 用 AsyncAdaptedQueuePool；
  异常分层映射 400/503。

═══ 六、API 契约（必须完全一致：17 条路径 / 19 个操作） ═══
身份：POST /api/v1/auth/register、POST /login、POST /refresh、POST /logout、GET /me
问答：POST /api/v1/questions、GET /api/v1/questions、GET /api/v1/questions/{id}、
      PATCH /api/v1/questions/{id}、POST /api/v1/questions/{id}/close、
      POST /api/v1/questions/{id}/answers、
      POST /api/v1/questions/{id}/vote、
      POST /api/v1/questions/{id}/answers/{aid}/vote、
      POST /api/v1/questions/{id}/comments、POST /api/v1/answers/{aid}/comments、
      POST /api/v1/answers/{id}/accept
标签：GET /api/v1/tags
声誉：GET /api/v1/users/{id}/reputation（本人可见，他人 403）
运维：GET /health（不依赖 DB）
要求：openapi.json 由脚本导出并纳入门禁，接口改动必须同步更新契约文件。

═══ 七、质量门禁（每一步都跑，贴真实输出） ═══
pytest -m "not integration" --cov=app --cov-report=term-missing --cov-fail-under=70
python -m coverage report --include="*/domain/*" --fail-under=90
ruff check .
mypy app                      # strict，0 错误
python scripts/export_openapi.py --check     # 契约防漂移

目标水位（阶段 3 收口时）：
- 单测 ≥180 个且全绿；集成用例另计（需 PG + Redis）
- 覆盖率 TOTAL ≥78%，domain 层 ≥95%
- ruff 0 违规；mypy --strict 0 错误（约 86 个文件）
- 端点与契约一致：17 paths / 19 operations
- alembic 迁移 8 个左右，每个都要人工审核过再 upgrade

═══ 八、分阶段路线图（每阶段结束停下汇报） ═══
阶段 0 工程重启（W1–W2）
  README、pyproject、requirements(dev)、.gitignore、目录骨架、/health、冒烟测试、
  GitHub Actions（lint→typecheck→test→openapi check）、docker-compose.yml（pg16+redis7）、
  GOALS.md、ADR-001..004 草稿、docs/PROGRESS.md
  验收：本地四道门禁全绿 + CI 变绿

阶段 1 Sprint 1 文档（W3–W5）
  用户故事地图、Product Backlog（逐条过 INVEST）、Gherkin 验收标准 ≥8 条、
  限界上下文图 + 聚合清单 + 术语表 ≥30 条、事件风暴产出
  验收：覆盖课程 Lab 2/3 全部提交物，我逐份看

阶段 2 Walking Skeleton（W7–W9）
  注册 → 登录 → 提问 → 列表 → 详情 端到端贯通；每个功能走"六步法"；
  版本化迁移；导出 openapi.json 交付前端
  验收：端到端可演示；覆盖率 ≥70%

阶段 3 核心特性（W11–W13）
  回答、投票、采纳、评论、标签、声誉（Celery 异步记账）；
  迭代 5 治理：登录锁定 423 + 问题编辑/关闭终态；
  前端 5 个页面（注册/登录/列表/详情/提问）；
  测试冲刺、契约测试、4 次 PR 评审记录、Sprint Review、Retro
  验收：达到第七节的目标水位

阶段 4 上线（不启动）
  只在 README 和 PROGRESS 里保留 TODO，不要写 Dockerfile、不要配 CD、不要碰监控。

═══ 九、每个功能都要走的"六步法" ═══
1 领域建模：聚合/值对象/领域事件/仓储端口，先写 docs/domain 的更新
2 领域层实现 + 单元测试（不碰 DB，纯内存）
3 应用层用例：事务边界、UnitOfWork、事件发布、权限判定
4 基础设施：ORM 映射、仓储实现、Alembic 迁移（生成后先给我看再 upgrade）
5 接口层：Pydantic schema、路由、错误码映射、鉴权依赖
6 集成测试 + 契约导出 + PROGRESS 追加记录
每一步都要先跑门禁再进下一步；任一步失败就停下来修，不许带病前进。

═══ 十、Claude Code 工作方式 ═══
- 第一件事：写 CLAUDE.md，把本提示词的铁律、命令、目录约定、提交规范固化进去；
  之后每个会话开始都先读它。
- 动手前先进 plan mode，产出 docs/plan/phase0-plan.md，列任务清单和验收点，等我确认。
- 探索代码用 subagent（Task/Explore），主线程只做决策和写代码，避免上下文被搜索结果淹没。
- 每完成一个阶段：把关键结论和"下一步"写进 docs/PROGRESS.md，然后我 /compact 或 /clear
  再继续——保证新会话能靠 PROGRESS + CLAUDE.md 接着做。
- 提交：type: 动词开头（feat/fix/test/docs/ci/chore），一次提交只做一件事；
  分支 feature/<issue>-<主题>，不直接提交 main。
- 每阶段汇报格式固定：
  ①改了哪些文件 ②跑了哪些命令 + 关键输出 ③哪些没验证 ④下一步等我说开始

═══ 十一、交付验收清单（我最后逐条核对） ═══
[ ] 目录结构与第四节一致，五个上下文目录都在
[ ] 17 路径 / 19 操作与 openapi.json 一致
[ ] pytest / ruff / mypy --strict / openapi --check 四项全绿，有真实输出
[ ] 覆盖率 TOTAL ≥78%、domain ≥95%，有报告
[ ] 8 个左右 Alembic 迁移，链式可 upgrade head
[ ] docker-compose 能起 pg16 + redis7
[ ] 前端 5 个页面可跑，代理指向后端端口
[ ] docs：PROGRESS、4 份 ADR、domain（上下文图/聚合/术语表）、sprint（故事地图/
    Backlog/Gherkin/PR 评审 4 条/评审清单/演示脚本/Retro）、api 说明、test 台账
[ ] README 的技术栈/端点/门禁数字与实际一致（不许写没做到的数字）
[ ] 阶段 4 保持未开始

═══ 十二、现在就开始做第一批（做完停下等我确认） ═══
1. git init + .gitignore + 目录骨架 + pyproject + requirements/requirements-dev
2. config/settings.py、shared 内核、app/main.py、GET /health、冒烟测试
3. docker-compose.yml（postgres:16 + redis:7，带 healthcheck）
4. .github/workflows/ci.yml（lint → typecheck → test → openapi check）
5. GOALS.md + ADR-001..004 + docs/PROGRESS.md 初版 + README 初版
6. 本地把四道门禁跑一遍，贴真实输出，然后停下来问我要不要进阶段 1。

如果环境里缺 Python 3.12 / Docker / PostgreSQL，先告诉我，不要自己装。
```

---

## 后续怎么接（不在首提示词里）

| 时机 | 你说的话 |
|:---|:---|
| 阶段 0 汇报后 | `阶段 0 验收通过，进阶段 1。先出 docs/sprint 的四个文档，写完停。` |
| 阶段 1 汇报后 | `文档过了，进阶段 2。按六步法先做 identity 的注册+登录，做完停。` |
| 阶段 2 中 | `继续下一个功能：提问` （一次一个，别让它批量做） |
| 阶段 3 收尾 | `做测试冲刺：补到 78% 覆盖率和 domain 95%，贴报告。` |
| 上下文变长 | `/compact`；换新会话前确认 `docs/PROGRESS.md` 已更新 |

三条最容易被跳过的检查，验收时逐条盯：

1. `mypy app` 是不是真的 strict（别被改成非 strict 或加了大量 `# type: ignore`）
2. `python scripts/export_openapi.py --check` 是否真的在 CI 里跑
3. 覆盖率数字是否来自刚跑的报告，而不是历史截图
