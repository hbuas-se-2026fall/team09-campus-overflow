# 管理后台前端交接

更新：2026-11-26。对齐团队仓库 `main` 的 F15 / F18 契约（检查基线 `bb14326`）。

## 正式后台

登录后打开 `/admin`。页面请求 `/api/v1/auth/me` 核验服务端实时身份，只有 `admin` 可加载管理界面。修改浏览器本地角色不能获得管理入口。身份请求失败支持重试；页面进入、窗口重新激活和每 30 秒刷新身份，权限最终由每个后端请求鉴权。

- 用户管理：分页、四角色筛选、公开资料链接、邮箱验证状态、角色修改二次确认；禁止修改自己。使用 `GET /api/v1/admin/users` 与 `PATCH /api/v1/admin/users/{user_id}/role`。
- 举报审核：分页、状态与问题/回答类型筛选；展示原因、举报人、处理人和处理说明。调用 `GET /api/v1/admin/reports` 与 `POST /api/v1/admin/reports/{report_id}/resolve`。
- 处置动作：驳回、关闭问题、软删除内容。回答举报不提供“关闭问题”，已处理举报不可再次处置。404/409/403 等错误展示后端原因。
- 真实后台只展示已交付的管理能力；社区统计、账号停用/恢复仍无后端接口。

F18 `ReportResponse` 没有举报目标正文，也没有回答所属 `question_id`；契约中没有按回答 ID 获取详情的 GET 接口。因此问题举报可以跳转问题，回答举报目前只能显示回答编号与原因。需要后端补充可审阅的目标摘要/正文和问题链接，才能在后台完整核查回答内容。不能通过遍历全站问题代替这个契约。

## 开发预览

`frontend` 目录执行 `pnpm run dev:admin`，访问 `/admin/preview`。该页面仍使用虚构数据，操作仅保存在内存，刷新还原。普通 `pnpm dev` 和生产构建没有演示路由。

演示的停用/恢复、统计功能不代表正式服务支持。正式验收请使用 `/admin`。

## 验证与交付

执行 `pnpm run test:coverage`、`pnpm run typecheck`、`pnpm run lint`、`pnpm run build`，再执行 `pnpm run test:e2e`。本机使用已安装 Chrome 时，先设置 `$env:PLAYWRIGHT_CHANNEL='chrome'`。

交付分支：`feat/frontend-admin`，远程 `team` 指向 `hbuas-se-2026fall/team09-campus-overflow`。只推送功能分支，待后端核查后合并。

F15 验收准备见 [frontend-f15-acceptance.md](frontend-f15-acceptance.md)。
