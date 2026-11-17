# CampusOverflow

> 校园问答知识社区 —— 沉淀教学答疑、量化学习参与

## 项目定位

面向高校场景的问答知识社区：学生按课程与标签提问、答疑，讨论沉淀为可复用的教学资产；声誉体系量化学习参与度，为过程性评价提供依据。

《软件工程》课程实践项目，按 DDD 方法论自主设计与实现，不参考任何开源项目代码。

## 技术栈

| 层次 | 选型 |
|:---|:---|
| 语言 | Python 3.12+ |
| Web 框架 | FastAPI + Uvicorn |
| ORM / 迁移 | SQLAlchemy 2.0（async）+ Alembic |
| 数据库 | PostgreSQL 16 |
| 缓存 / Broker | Redis 7（db0 存 Refresh 令牌、db1 作 Celery broker） |
| 数据校验 | Pydantic v2 |
| 异步任务 | Celery（声誉异步记账） |
| 测试 | pytest + pytest-cov |
| 代码质量 | ruff + mypy --strict |
| CI | GitHub Actions |
| 部署 | Docker Compose |
| 前端 | React 18 + TypeScript 5 + Vite + Ant Design + React Query + Zustand |

## 架构决策

| 决策 | 说明 |
|:---|:---|
| 限界上下文纵切 | 按 5 个子域分包：identity / qa / course / reputation / discovery，每个上下文内再分 domain / application / infrastructure / interfaces（ADR-002） |
| 数据库选型 | PostgreSQL 16 替代课程默认 MySQL 8：JSONB、全文检索、asyncpg 异步生态（ADR-001） |
| 单体 + 模块化 | 单进程部署，靠目录与 import 纪律维持上下文边界（reputation 对 qa 零 import，仅经事件载荷通信） |
| 认证 | JWT Access 15min + Refresh 7d 存 Redis（GETDEL 原子轮换、可吊销）+ RBAC；bcrypt 口令哈希 |
| 主键 | UUID 全局主键 |
| 领域分层 | domain 层纯 Python，不 import FastAPI / SQLAlchemy；聚合刻意收小 |
| 并发一致性 | 库级约束兜底：投票复合唯一索引 `(user_id, target_type, target_id)`、部分唯一索引保证"一题一采纳" |
| 连接池与容量 | 哨兵式池：`db_pool_size=0` 走 NullPool（测试/CI 零影响），`>0` 启用 AsyncAdaptedQueuePool；异常分层 400/503（ADR-003） |
| 声誉记账 | Celery 异步 + 流水幂等（唯一索引 `(source, event_id)`）+ `task_acks_late=True` 至少一次投递（ADR-004） |
| 会话时序 | 路由与依赖统一 `Depends(get_session, scope="function")`，保证提交先于响应发送 |
| 内容治理 | 问题关闭为终态（投票/回答/评论/采纳/编辑全冻结；条件 UPDATE 库级兜底）；登录失败 5 次/15 分钟 Redis 锁定 → 423 |

决策全文见 [docs/adr/](docs/adr)：ADR-001 / ADR-002 / ADR-003 / ADR-004。

## 功能现状

后端已交付 **26 条路径 / 29 个操作**（契约见根目录 [openapi.json](openapi.json)，人读说明见 [docs/api/api-contract-notes.md](docs/api/api-contract-notes.md)）：

| 域 | 端点 | 说明 |
|:---|:---|:---|
| 身份 | `POST /api/v1/auth/register` | 学生（学号+邮箱）/ 教师（工号）分流，bcrypt 哈希，重复注册 409 |
| | `POST /api/v1/auth/login` | 学号/工号 + 密码 → JWT 双令牌（失败超限 **423** 临时锁定：5 次/15 分钟窗口，防枚举统一计数） |
| | `POST /api/v1/auth/refresh` | 轮换：旧 Refresh 原子消耗后签发新对 |
| | `POST /api/v1/auth/logout` | 吊销 Refresh，幂等 204 |
| | `GET /api/v1/auth/me` | 当前用户信息（需 Bearer Access） |
| 问答 | `POST /api/v1/questions` | 发布问题（登录用户，可带至多 5 个标签） |
| | `GET /api/v1/questions` | 列表（访客可用，分页；支持 `q` 搜索、`tag`/`status`/创建时间筛选与 `latest`/`votes` 排序） |
| | `GET /api/v1/questions/{id}` | 详情（访客可用，答案按采纳优先排序，含标签与三级评论） |
| | `GET /api/v1/questions/{id}/related` | 相关问题推荐（按标签共现，访客可用） |
| | `PATCH /api/v1/questions/{id}` | 编辑问题（仅提问者；仅标题+正文，部分更新；已关闭 409） |
| | `POST /api/v1/questions/{id}/close` | 关闭问题（仅提问者，终态；重复关闭/已采纳 409；未采纳悬赏全额退款） |
| | `POST /api/v1/questions/{id}/answers` | 发布回答 |
| | `POST /api/v1/questions/{id}/vote` | 问题投票（顶/踩） |
| | `POST /api/v1/questions/{id}/answers/{aid}/vote` | 回答投票（重复票/改票一律 409） |
| | `POST /api/v1/questions/{id}/comments` | 问题评论 |
| | `POST /api/v1/answers/{aid}/comments` | 回答评论 |
| | `POST /api/v1/answers/{id}/accept` | 采纳最佳答案（仅提问者，非作者 403 / 重复采纳 409；联动结算悬赏） |
| 标签 | `GET /api/v1/tags` | 标签目录（访客可用，码点序、同名唯一归并） |
| 徽章 | `GET /api/v1/users/{id}/badges` | 用户徽章与活跃统计（公开；回答数/采纳率/最长连续活跃） |
| 悬赏 | `POST /api/v1/questions/{id}/bounty` | 发起教师悬赏（仅教师 403；关闭/已采纳/余额不足/重复悬赏 409） |
| | `GET /api/v1/questions/{id}/bounty` | 查询进行中的悬赏（公开；无则 `null`） |
| 积分 | `GET /api/v1/users/me/points` | 查询本人可消费积分余额与流水（需登录；教师首次访问惰性发放 100 分） |
| 声誉 | `GET /api/v1/users/{id}/reputation` | 本人声誉总值与变动流水（他人 403） |
| 榜单 | `GET /api/v1/leaderboard` | 声誉排行榜（公开；`week`/`month`/`semester`；60s 热榜缓存，Redis 故障降级直查库） |
| 通知 | `GET /api/v1/notifications` | 本人通知列表（分页 + 未读筛选，含可选 `question_id`） |
| | `GET /api/v1/notifications/unread-count` | 未读通知数 |
| | `POST /api/v1/notifications/{id}/read` | 单条标记已读（幂等 204） |
| | `POST /api/v1/notifications/read-all` | 全部标记已读 |
| 运维 | `GET /health` | 存活探针（无 DB 依赖） |

已关闭的问题为**终态**：投票（题/答）、新增回答、评论、采纳、编辑一律 409（库级条件 UPDATE 并发兜底）。

声誉记分规则：回答被赞 +10、回答被踩 −2、问题被赞 +5、问题被踩 −2、回答被采纳 +15；自投不计分。异步结算有约 0.5–2s 延迟，前端勿假设同步可见。

### 里程碑

| 阶段 | 主题 | 状态 |
|:---|:---|:---|
| 阶段 0 | 工程重启（工具链 / 骨架 / CI / Compose） | 完成 |
| 阶段 1 | Sprint 1 文档（故事地图 / Backlog / Gherkin / 领域模型） | 完成（1.1–1.4 产出完成；1.4 检测复核已完成） |
| 阶段 2 | Walking Skeleton（注册→登录→提问→列表→详情 + 契约交付） | 完成 |
| 阶段 3 | 核心特性（回答 / 投票 / 采纳 / 评论 / 标签 / 声誉 + Celery / 测试冲刺 / Sprint Review / 迭代 5 治理：登录锁定 + 问题编辑关闭） | 完成 |
| 阶段 4 | 上线部署（容器化、CI/CD、监控告警、运维手册） | 未开始 |

明细与验收证据见 [docs/PROGRESS.md](docs/PROGRESS.md)。

### 质量门禁（当前实测）

| 门禁 | 结果 |
|:---|:---|
| pytest | CI 单测口径 298 passed（总用例 482 条，184 条 integration 需 PG+Redis） |
| 覆盖率 | TOTAL 83.40% ≥ 70；domain 层 94% ≥ 90 |
| ruff | 0 违规 |
| mypy --strict | 0 错误（135 文件） |
| 契约防漂移 | `openapi.json` 与代码一致（CI `--check` 门禁；26 paths / 29 ops） |

## 目录结构

```
app/
├── config/settings.py            # Pydantic Settings（.env 覆盖）
├── platform/http/                # Web 中间件、错误映射、会话依赖
├── shared/                       # 引擎、异常处理、文本校验等共享内核
└── contexts/
    ├── identity/                 # 注册 / 登录 / JWT / RBAC
    ├── qa/                       # 问题 / 回答 / 投票 / 采纳 / 评论 / 标签 / 徽章 / 悬赏 / 积分
    ├── reputation/               # 声誉流水 + 排行榜 + Celery 记账
    └── discovery/                # 站内通知中心（F04）
alembic/                          # 迁移脚本（生成后须人工审核才 upgrade）
tests/                            # 单元 + 集成测试
docs/                             # PROGRESS / adr / domain / sprint / api / test / plan
frontend/                         # React 18 + TS + Vite（注册 / 登录 / 列表 / 详情 / 提问）
scripts/                          # openapi 导出与门禁校验、一键启动器源码
docker-compose.yml                # 本地 db + redis
CampusOverflow-Launcher.exe       # Windows 一键启动器（见下）
```

## 快速开始

### 环境要求

- Python 3.12+
- Docker（PostgreSQL 16 + Redis 7 由 compose 拉起）
- Node.js 20+ 与 pnpm（仅前端需要）

### 方式一：一键启动（Windows）

双击仓库根 `CampusOverflow-Launcher.exe`（或运行 `scripts/launcher/campus_launcher.ps1`）：自动起 db/redis → `alembic upgrade head` → 三个窗口分别起 API / Celery worker / 前端 → 打开浏览器。

启动器会自动避开 Windows Hyper-V 动态保留端口。只想做环境自检：

```powershell
.\scripts\launcher\campus_launcher.ps1 -Check
```

### 方式二：手动启动后端

```powershell
# 1. 依赖
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt

# 2. 基础设施（db + redis，等 healthcheck 通过）
docker compose up -d

# 3. 配置（可选：复制 .env.example 为 .env 覆盖，字段均有开发默认值；生产必须覆盖 jwt_secret）
#    db_port / redis_port（Windows 若 5432/6379 落入 Hyper-V 保留段可改用 15432/16379）
#    database_url / redis_url / celery_broker_url / jwt_secret
#    db_pool_size（0=NullPool 默认；>0 启用连接池，见 ADR-003）

# 4. 迁移（脚本变更须人工审核后执行）
alembic upgrade head

# 5. 起 API
uvicorn app.main:app --host 127.0.0.1 --port 8123

# 6. 起声誉异步 worker（Windows 必须 solo 池）
celery -A app.contexts.reputation.infrastructure.celery_app:celery_app worker --pool=solo -l info
```

接口与文档：

- Swagger UI：http://127.0.0.1:8123/docs
- 契约文件：http://127.0.0.1:8123/openapi.json
- 存活探针：http://127.0.0.1:8123/health

### 启动前端

```powershell
cd frontend
pnpm install
pnpm dev          # Vite 开发服务器，/api 代理到 http://localhost:8123
```

代理目标可用环境变量 `VITE_API_TARGET` 覆盖（与后端端口保持一致）。

### 本地门禁（提交前自查）

```powershell
pytest -m "not integration" --cov=app --cov-report=term-missing --cov-fail-under=70
python -m coverage report --include="*/domain/*" --fail-under=90
ruff check .
mypy app
python scripts/export_openapi.py --check    # 契约防漂移
```

集成测试需 PostgreSQL + Redis 在跑：`pytest -m integration`。

## 文档索引

| 文档 | 内容 |
|:---|:---|
| [docs/PROGRESS.md](docs/PROGRESS.md) | 里程碑状态与逐条变更记录 |
| [docs/adr/](docs/adr) | 4 份架构决策记录 |
| [docs/domain/](docs/domain) | 限界上下文图、聚合清单、术语表 |
| [docs/sprint/](docs/sprint) | 故事地图、Backlog、Gherkin 验收标准、PR 评审记录、评审清单、演示脚本、Retro |
| [docs/api/api-contract-notes.md](docs/api/api-contract-notes.md) | 契约消费说明与错误形态速查 |
| [docs/test/](docs/test) | 各步骤测试台账（含 15 路暴力测试记录） |
| [docs/plan/phase3-plan.md](docs/plan/phase3-plan.md) | 阶段 3 实施计划 v3 |

## 当前版本

v0.1.0 —— 阶段 0–3 已收口（含迭代 5：登录锁定 + 问题编辑/关闭），阶段 4 上线未开始。
