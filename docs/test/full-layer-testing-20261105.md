# 全层级测试台账（2026-11-05）

> 范围：对当前工作树执行单元 / 集成 / 组件 / 验收 / UI 五层测试，不改产品代码。
> 环境：Windows 11 · Python 3.12 venv · PostgreSQL/Redis（docker compose，均 healthy）· Node 22 + pnpm · 前端 Vite 6.4.3。
> 基线：工作区干净（`git status` 无改动）后开工；本轮新增仅前端测试文件与测试配置。

## 一、结果总表

| 层级 | 命令 | 结果 | 门槛 |
|:--|:--|:--|:--|
| 后端单元 | `pytest -m "not integration" --cov=app --cov-report=term-missing` | **204 passed**（122 deselected），TOTAL **84%**（2055 语句 / 338 未覆盖） | ≥70% ✅ |
| 核心聚合 | `coverage report --include="*/domain/*" --fail-under=90` | **95%**（444 语句 / 22 未覆盖） | ≥90% ✅ |
| 后端集成 | `pytest -m integration --ignore=tests/acceptance` | **119 passed**（156.95s） | 全绿 ✅ |
| 后端验收 | `pytest tests/acceptance` | **3 passed**（10.63s） | 全绿 ✅ |
| 前端组件/单元 | `pnpm run test` | **39 passed / 12 files**（新增 18 条组件用例） | 全绿 ✅ |
| 前端类型 | `pnpm run typecheck` | 0 错误 | 0 ✅ |
| 前端 lint | `pnpm run lint` | 0 warnings / 0 errors（35 文件） | 0 ✅ |
| UI 端到端 | 浏览器自动化（真实 uvicorn:8500 + Vite:5173 + Celery worker） | **6/6 场景 PASS** | 全通过 ✅ |

后端三层合计 **326 passed**，与 2026-11-05 批次 ⑦ 的基线一致。

## 二、验收测试覆盖（既有 3 条）

| 用例 | 链路 | 结果 |
|:--|:--|:--|
| `test_student_learning_loop` | 注册→登录→提问→回答→投票→评论→采纳→详情呈现 | PASS |
| `test_guest_can_read_but_cannot_write` | 访客读列表/详情/标签 200，写操作 401 | PASS |
| `test_closed_question_freezes_interactions` | 关闭后回答/评论/投票/采纳/编辑全部 409，详情仍可读 | PASS |

## 三、本轮新增：前端组件测试

**基础设施（2 个文件）**

| 文件 | 内容 |
|:--|:--|
| `frontend/src/test/setup.ts`（新增） | `@testing-library/jest-dom/vitest` 匹配器；jsdom 缺口的 `matchMedia` / `ResizeObserver` 垫片；`afterEach` 执行 RTL `cleanup` + 清 localStorage |
| `frontend/vite.config.ts`（修改） | `defineConfig` 改自 `vitest/config`，新增 `test` 段：`environment=jsdom`、`setupFiles=./src/test/setup.ts`、`testTimeout=20000`（Windows + antd 环境实测单用例可达 11s，5s 默认值会假超时） |

**组件用例（6 个文件 / 18 条）**

| 文件 | 用例数 | 覆盖点 |
|:--|:--|:--|
| `frontend/src/components/AppShell.test.tsx` | 2 | 访客态仅公共导航+登录；登录态显示学号、发布/声誉入口、退出 |
| `frontend/src/pages/LoginPage.test.tsx` | 4 | 表单渲染；空提交必填校验；成功写入 token/user 并跳转；失败提示并清理会话 |
| `frontend/src/pages/RegisterPage.test.tsx` | 3 | 学生/教师身份切换字段；弱密码（缺数字）拦截；注册成功跳转登录 |
| `frontend/src/pages/QuestionsPage.test.tsx` | 3 | 列表标题/标签/总数渲染；搜索过滤当前页；加载失败空状态 |
| `frontend/src/pages/TagsPage.test.tsx` | 3 | 标签渲染；无标签空状态；加载失败空状态 |
| `frontend/src/pages/ReputationPage.test.tsx` | 3 | 总声誉+流水（+10/+15）；无流水空状态；加载失败空状态 |

测试策略：页面组件通过 `vi.mock` 替换 API/hook 边界（`../hooks/useQuestions`、`../hooks/useReputation`、`../api/auth`），用 `MemoryRouter + Routes` 验证真实导航；不 mock antd 内部实现。踩坑记录：antd 会把两字中文按钮渲染成「登 录」「退 出」，无障碍名匹配需用 `/登\s*录/`。

## 四、UI 端到端（浏览器实测）

环境：`.venv` uvicorn `127.0.0.1:8500` + Celery worker `--pool=solo` + Vite `localhost:5173`（`VITE_API_TARGET=http://127.0.0.1:8500`）。

| # | 场景 | 结果 | 证据 |
|:--|:--|:--|:--|
| 1 | 访客打开问题广场 | PASS | 列表与分页正常渲染，总数 843 |
| 2 | 注册学生（20267777 / ui-20267777@campus.edu.cn / Passw0rd8） | PASS | 注册后跳转 `/login` |
| 3 | 登录 | PASS | 右上角显示用户标识 20267777 |
| 4 | 发布问题（真实技术内容：PostgreSQL 复合唯一索引防重复投票） | PASS | 列表总数 843→844，新问题在顶部，详情可打开 |
| 5 | 详情页回答 + 点赞 | PASS | 回答数 0→1，票数 1 |
| 6 | 我的声誉 | PASS | 未登录访问被重定向 `/login`；登录后显示「我的声誉 / 当前总声誉 0」 |

说明：总声誉 0 为**预期**——该回答的点赞者是作者本人，自投不计分（记分规则）。测试产生的用户与问题为真实技术内容，按项目数据纪律保留，不清理。

**环境观察（非产品缺陷）**：worker 启动后先消费到一条历史遗留的陈旧投票消息（user_id 已从 users 表删除），外键约束拒绝并重试——即 ADR-004 记录的无 DLQ 行为；与本轮 UI 结果无关，未造成数据损坏。

## 五、遗留与建议（只报告，未改动）

1. `QuestionDetailPage` 尚无组件级测试（本轮覆盖 6 个页面/组件，详情页交互最复杂，建议下一轮补充）。
2. UI 测试目前为一次性浏览器自动化，未沉淀为可重复脚本（Playwright/Cypress 未引入，避免新增依赖）。
3. 前端组件测试在 Windows 下偏慢（18 条约 35s），属 jsdom + antd 固有开销，已用 20s 单用例超时兜底。
