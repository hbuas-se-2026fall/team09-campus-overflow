# F15 前端联调准备与后端增量对照

日期：2026-11-26。跟踪 [Issue #11](https://github.com/hbuas-se-2026fall/team09-campus-overflow/issues/11)。核对团队仓库 `main`：`bb14326`，F15 实现来自 PR #7。前端交付到 `feat/frontend-admin`，不直接合并 main。

## 前端实现范围

| 后端交付 | 前端对应入口 | 状态 |
| --- | --- | --- |
| F13 软删除 | 问题/回答作者的删除确认；删除问题后返回列表；已采纳内容隐藏删除入口；关闭问题允许作者删除未采纳内容 | 已实现 |
| F14 二级回复 | 题评、答评按 `parent_id` 分组；仅一级评论显示回复入口；回复请求携带父评论 ID；`comment_replied` 通知 | 已实现 |
| F15 四角色 | 学生/教师/助教/管理员身份展示、服务端实时身份刷新、公开注册仍只允许学生/教师 | 已实现 |
| F15 回答认证 | 问题详情认证/取消认证；显示认证人和时间；学生隐藏入口；关闭问题隐藏入口；403/409 错误反馈；`answer_verified` 通知 | 已实现 |
| F15 用户管理 | `/admin` 服务端身份核验、用户分页和角色筛选、修改他人角色、禁止改本人 | 已实现 |
| F16 课程与选课 | `/courses` 公开课程列表与学期筛选；教师/管理员创建课程；学生选课；教师/助教/管理员查看名录 | 已实现 |
| F17 课程关联 | 发布/编辑问题关联或解绑课程、按课程筛选、课程贡献榜 | 已实现 |
| F18 举报审核 | 问题/回答举报原因表单、管理员举报列表和处理动作 | 已实现；回答内容预览受接口限制 |

继续沿用 React / Ant Design / React Query，页面按路由加载；本次不新增依赖。多标签请求使用 `tag=a&tag=b`，与 FastAPI 的重复参数契约保持一致。

## 测试环境启动（按仓库配置整理，尚未在本机完成真库联调）

要求 Python 3.12+、Node 22+、pnpm、已启动的 Docker Desktop。使用隔离的验收数据库，勿直接对共享生产库执行迁移。

在仓库根目录：

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
docker compose up -d db redis
.venv\Scripts\alembic.exe upgrade head
.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8123
```

另开终端运行前端：

```powershell
cd frontend
pnpm install --frozen-lockfile
pnpm dev
```

Vite 默认将 `/api` 转发至 `http://localhost:8123`；连接团队部署环境时，在前端本地环境文件设置 `VITE_API_TARGET`。后端健康检查 `/health`，接口文档 `/docs`，迁移 head 应为 `78debaff54c7` 或后续版本。

如果验收声誉异步流水，另开终端运行：

```powershell
.venv\Scripts\celery.exe -A app.contexts.reputation.infrastructure.celery_app:celery_app worker --pool=solo -l info
```

F15 认证通知由后端同事务写入，不依赖声誉 Worker；取消认证不发送通知，认证不增加声誉。

## 四角色测试账号准备

账号密码由后端/环境维护者通过私有渠道分发；本文和公开 Issue 均不填写密码。

1. 学生、教师：使用 `/register` 自助注册；另外准备两个不同学生账号，分别作为提问者和回答者，验证非自操作通知。
2. 管理员：环境维护者在验收库运行 `scripts/seed_admin.py`。环境变量为 `ADMIN_EMAIL`、`ADMIN_STAFF_ID`、`ADMIN_PASSWORD`。工号格式为 `T` 加 4–8 位数字。密码从本地安全输入或私密环境配置提供，禁止提交入库/贴在 Issue 中。脚本对已有管理员幂等，提权已有账号时保留原登录凭据，不负责重设密码。
3. 助教：先注册普通测试账号，再由管理员登录 `/admin` 为该账号授予 `ta`；仍用原学号/工号登录。公开注册不能选择 `ta` 或 `admin`。
4. 准备一个额外管理员账号以验证角色授予/撤销；当前管理员不能修改自己的角色。
5. 后端向 SM 确认环境 URL、部署提交、数据库迁移版本和可用角色清单；密码单独发给实际验收人员。

## F15 联合验收清单

| 场景 | 预期 |
| --- | --- |
| 访客访问管理后台 | 跳转登录 |
| 学生/教师/助教直接访问 `/admin`，或修改本地存储为 admin | 服务端身份核验后拒绝，不请求管理列表 |
| 教师、助教、管理员认证未认证回答 | POST verify 成功；显示认证标记、认证人、时间；刷新后保持 |
| 上述角色取消认证 | DELETE verify 成功；清空认证展示；刷新后保持 |
| 学生直接调用认证 API | 403；页面不提供认证按钮 |
| 重复认证/重复取消 | 分别幂等 200/204；重复认证保留首次认证人和时间；仅首次非自操作发一条通知 |
| 认证自己的回答 | 状态变更成功，不给自己发通知 |
| 问题关闭/内容删除 | 关闭态不提供认证入口；并发关闭返回409；已删返回404，不显示假成功 |
| 管理员给他人改角色 | 列表同步；目标旧令牌下一次 API 请求按新角色鉴权；页面回到前台/刷新后同步 |
| 操作过程中被降级 | 后端403；页面显示错误并重新读取身份、移除受限入口 |
| 角色显示与教师悬赏 | 四角色名称正确；悬赏仍只向 teacher 开放，ta/admin 不扩权 |
| 回答者的通知中心 | 展示“认证了你的回答”，可进入相关问题；取消认证无新增通知 |

## 证据边界与团队阻塞

本轮本地执行结果（2026-11-26）：

| 检查 | 实际结果 |
| --- | --- |
| `pnpm run typecheck` | 通过 |
| `pnpm run lint` | 通过 |
| `pnpm run test:coverage` | 13 个测试文件、45 个测试通过；现有覆盖率门禁范围内语句/行覆盖率 93.29%、分支 86.74%、函数 87.87% |
| `pnpm run build` | 通过；最大单个 JS 分块 289.07 kB，无 500 kB 警告 |
| `PLAYWRIGHT_CHANNEL=chrome pnpm run test:e2e` | 开发与生产项目合计 45 passed、5 skipped（演示与生产环境隔离的条件跳过） |

测试入口为 `frontend/e2e/backend-updates.spec.ts`、`frontend/e2e/admin.spec.ts`、`frontend/e2e/question-flow.spec.ts` 和 `frontend/src/api/contract.test.ts`。

自动化浏览器测试使用模拟 API，验证前端请求、界面与错误处理；不能据此宣布真实数据库鉴权、通知去重、并发或 PO 业务验收已完成。后端已有测试台账不是本轮联合验收结果。

本机检查时 Docker Linux Engine 不可连接，未创建测试账号、未执行真实数据库迁移。待后端提供运行环境和四角色账号，前端即可参与联调；建议安排 30–60 分钟走查，不含环境修复和新发现问题的修复时间。PO 验收负责人和具体时间尚待团队指定。

F18 额外契约缺口：回答举报没有回答正文、问题 ID 或可获取回答详情的 GET 接口；后台目前展示回答编号、原因及处理结果。建议后端在工单中提供目标摘要/正文和 `question_id` 或提供详情接口。此项不阻塞 F15，但阻塞 F18 的完整内容核查体验。

## 需要记录的验收结果

执行后由 SM/PO 补充：环境 URL / 前后端提交 / 验收人 / 角色账号编号（不含密码）/ 日期 / 逐项实际结果 / 截图或缺陷链接。未经 PO 确认不要关闭 Issue #11。
