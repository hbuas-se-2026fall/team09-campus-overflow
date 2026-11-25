# CampusOverflow API 契约说明（给前端）

> 配套文件：仓库根 [`openapi.json`](../../openapi.json)（由 `scripts/export_openapi.py` 生成，OpenAPI 3.1）。
> 本文写的是 **schema 表达不了的约定与全局行为**，前端必读。

## 一、生成与防漂移（重要）

- `openapi.json` 由 `python scripts/export_openapi.py` 生成，**任何 API 变更后必须重跑**；
- CI 门禁会执行 `--check` 比对：代码改了契约没重新导出 → **CI 红**；
- 依赖升级（FastAPI/Pydantic）也可能改变 schema 结构触发门禁——这是特性（提醒同步），重跑导出即可；
- `.env` 中**不要覆盖 `app_name`**——`openapi().info.title` 取自它，覆盖后契约文件与 CI 门禁冲突。

## 二、两条接口约定

1. **`extra=forbid`**：所有请求体 schema 禁止多余字段——**多塞任何字段直接 422**。前端请求体严格按 schema 字段发送。
2. **XSS 由前端渲染时转义**：后端对文本**原样存储、原样回显**（含 `<script>`、emoji 等）。所有用户输入内容在 HTML 渲染时必须转义（R-15 统一口径）。

## 三、错误形态速查

| 状态码 | `detail` 形态 | 来源 | 前端处理 |
|:--|:--|:--|:--|
| 422 | **数组** `[{type, loc, msg}]`（不回显 input） | Pydantic 校验（含 extra=forbid、tags 类型/结构/原始数量 >20） | 逐项展示 msg。⚠️ schema 声明的 `input`/`ctx` 是 FastAPI 内置 ValidationError 模型残留，**实际响应永不含这两个键**，请以 type/loc/msg 为准 |
| 422 | **字符串**（中文业务语义，如"至多 5 个标签…""标签含不支持的字符…""父评论不属于当前对象""评论仅支持二级回复，不可回复二级评论"） | 领域值对象与实体不变式校验（Title/Body/Tag、标签去重上限、F14 评论二级回复归属与层级） | 直接展示该句。**tags 两种 422 形态都要处理**：类型/结构错=数组形，语义违规=字符串形 |
| 401 | 字符串（如"令牌无效或已过期"） | Bearer 依赖层 | 跳登录页 |
| 400 | 字符串（如"请求数据无法被数据库接受…""验证码无效或已过期"） | 数据库兜底 / 邮箱验证码校验失败（错码/过期/超 5 次） | 提示检查输入或重发验证码 |
| 413 | 字符串"request body too large" | 1 MiB body 上限中间件 | 提示内容过大 |
| 404 | 字符串（如"问题不存在""回答不存在""评论不存在""用户不存在""课程不存在"） | 业务语义 | 展示空态 |
| 409 | 字符串（如"已对该对象投过票"…/"该问题已有采纳答案"/"问题已关闭"/"已关闭的问题不可编辑"/"邮箱已完成验证"/"该问题已有采纳答案，不可删除"/"已采纳的回答不可删除"/"不可修改本人角色"/"课程编号已存在"/"已选修该课程，请勿重复选课"） | 业务冲突：重复投票/改票、重复采纳、已关闭问题全冻结、邮箱已验证再发送、删除已采纳问题或回答、不可修改本人角色、重复课程编号、重复选课 | 展示提示；**勿自动重试** |
| 423 | 字符串"尝试次数过多，账号临时锁定，请稍后再试" | 登录失败超限（US-L04：5 次/15 分钟窗口，成功登录即清零） | 提示稍后再试；**勿自动重试** |
| 429 | 字符串（如"发送过于频繁，请 60 秒后再试"） | 邮箱验证码发送冷却（F10：60s 冷却） | 展示倒计时，勿自动重试 |
| 405 | 标准 Method Not Allowed | 方法面 | —（请求方式写错才会遇到） |
| 503 | 字符串"服务暂时不可用，请稍后重试" / "邮箱验证服务暂时不可用…" | 数据库/Redis/邮件发送不可达或未配置（F10 / 容量分层） | **可重试**（指数退避），勿当业务错误 |

**⚠️ 全局错误码不在 schema 内**：`openapi.json` 各路由 `responses` 只声明了 200/201/204/422；上表中的 401/400/404/405/409/413/423/429/503 来自中间件、依赖层与路由映射，**生成类型时看不见，但真实存在，前端必须处理**。

## 四、分页契约（`GET /api/v1/questions`）

- 请求：`page ≥ 1`（默认 1）、`page_size` 1~100（默认 20）
- 筛选（F01/US-Q07，2026-11-05）：
  - `tag` **可重复传参**（`?tag=a&tag=b`），多个标签为 **AND**；按标签归并键匹配，**大小写不敏感**；同一 key 重复传参自动去重
  - `status`：`open` / `closed`；**省略 = 全部**（向后兼容）
  - `created_from` / `created_to`：创建时间**闭区间**，**必须带时区**；naive → 422；`created_from > created_to` → 422
  - 空 `tag=`（空串）、非法字符标签、非法时间格式、tag 去重后超过 5 个（与每题标签上限一致）→ 422
  - 筛选条件同时作用于 `total` 统计与当前页数据（同口径）；筛选后超总页仍 **200 空列表**
- 搜索（F02，2026-11-12）：
  - `q`：匹配**标题 + 正文**，大小写不敏感；空串/纯空白等价于不传
  - 至多 **100 字**；含制表符/换行/回车或其它控制字符 → **422 字符串形**
  - `%`、`_`、`\` 按**字面**匹配（不是通配符）
  - 可与 `tag`/`status`/`created_from`/`created_to`/`sort`/分页任意组合，`total` 与结果同口径
- 响应：`{items, total, page, page_size, total_pages}`；**空库 `total_pages = 0`**
- 排序：`created_at` 新→旧（同刻按 id 定序，跨页零重复零漏项）；`sort=votes` 按净票数，可与全部筛选组合
- 超总页 → **200 空列表**（非 404）

## 四点五、相关问题推荐（`GET /api/v1/questions/{id}/related`，F03）

- 访客可用；返回 `QuestionListItem[]`，**无分页、无 `total`**
- `limit` 1~10，默认 5；越界 → **422**
- 排序：标签重合数降序 → 净票数降序 → 创建时间降序 → id 降序；**排除自身**
- 无标签问题 → **200 空数组**；问题不存在 → **404**（detail `"问题不存在"`）
- 关闭问题仍可被推荐（与列表 `status` 口径一致，不额外过滤）

## 四点六、声誉查询口径（`GET /api/v1/users/{user_id}/reputation`）

- **仅本人**（v3.1 裁定 4）：他人查询 → **403**（author_id 在问题/回答已公开，无存在性可泄露）；未登录 401
- **最终一致**：投票/采纳后声誉流水经 Celery **异步**落账（实测结算延迟亚秒~1.3s）——前端**勿假设 204 后同步可查**，展示前轮询或容忍短暂滞后
- `entries` 不分页（流水量小）；`total` 可为负（踩分计入）；空账 `total=0` + 空列表
- 分值口径唯一出处：后端 `reputation/domain/ledger.py` 常量（答赞 +10 / 答踩 −2 / 题赞 +5 / 题踩 −2 / 采纳 +15，自投不计分）

## 四点七、会话与登出口径（`POST /api/v1/auth/logout`）

- logout 吊销 **Refresh 令牌**，幂等 **204**（无效/已吊销令牌同样 204，不暴露令牌状态）；
- **Access 令牌不进黑名单**：登出后其在剩余有效期（≤15 分钟）内仍可通过认证——无状态 JWT 的标准取舍（业界惯例）；前端登出即清本地令牌，勿依赖服务端立即失效。

## 四点八、排行榜（`GET /api/v1/leaderboard`，F05）

- **公开**，无需登录；空榜返回 200 + `entries=[]`
- `period`：`week`（默认）/ `month` / `semester`
- 学期边界（Asia/Shanghai）：春季 3/1–8/1，秋季 9/1–次年 2/1；**2 月归上一秋季、8 月归当年春季**
- 得分 = 期间 `SUM(delta)` **净得分**（含负）；名次为 **同分同名次**（1,1,3），同分按 `user_id` 升序稳定
- `limit` 1~100，默认 10；非法 `period`/越界 `limit` → 422
- 响应：`{period, period_start, period_end, entries:[{user_id, display_name, score, rank}]}`（展示名随 F11 实时回填，不受榜单 60s 缓存影响）
- **热榜缓存（F08，2026-11-17）**：服务端可能命中 Redis 短时缓存，**最大陈旧 = TTL 60s + 声誉 Celery 落账延迟（亚秒~约 1.3s）**；投票/采纳后 60s 内榜单可能仍是旧快照，前端勿假设立即可见。缓存故障自动降级直查 PG，仍返回 200，不会因 Redis 不可用变成 503。

## 四点九、用户徽章（`GET /api/v1/users/{id}/badges`，F06）

- **公开**，无需登录；用户不存在 → **404**（detail `"用户不存在"`）
- 实时计算，不物化；响应含 `answer_count`、`accepted_count`、`acceptance_rate`、`longest_streak_days`、`badges[]`（F13 起全量剔除已软删除问题/回答及挂在已删宿主上的评论与投票，历史连续活跃天数可随之下降）
- 徽章族与阈值：
  - 回答数：5 / 20 / 50（铜/银/金）
  - 采纳率：回答数 ≥5 才评估，50% / 70% / 90%
  - 连续活跃：**历史最长**连续天数 3 / 7 / 30；活跃按 Asia/Shanghai 自然日，含发帖/回答/评论/投票
- 徽章 `code` 形如 `answers_5`、`acceptance_70`、`streak_3`；同族可同时命中多档
- 无活动 → 200 + `badges=[]`（非 404）

## 四点十、通知中心（`/api/v1/notifications`，F04）

- 全部端点**要求登录**（401 未认证）；收件人恒取令牌当前用户
- `GET ""`：分页 `page/page_size/unread_only`，`created_at` 新→旧；响应 `{items,total,page,page_size,total_pages}`
- `GET /unread-count`：`{count}`
- `POST /{id}/read`：幂等 **204**；非本人/不存在 → **404**（不泄露存在性）
- `POST /read-all`：`{updated}`（本次由未读转为已读的条数，幂等）
- 通知类型：`answer_posted` / `answer_accepted` / `answer_verified`（F15）/ `comment_created` / `comment_replied`（F14）；`target_type` 支持 `question` / `answer` / `comment`（F14）；自己操作自己的内容不产生通知
- 每条通知含可选 `question_id`（新写入的通知无论目标为问题、回答还是评论均带所属 `question_id`，存量历史通知可能为 `null`）
- 同事件对同一收件人只落一条（库级唯一键），重复触发不会重复插入

## 四点十一、教师悬赏（`/api/v1/questions/{id}/bounty`）与个人积分（`/api/v1/users/me/points`，F07）

- `POST /api/v1/questions/{id}/bounty`：**仅教师**（学生 403）；body `{"amount": 1~1000000}`
  - 问题不存在 404；问题已关闭 409；**问题已有采纳答案 409**；余额不足 409；同一问题已有进行中悬赏 409
  - 成功 201，返回 `{id,question_id,teacher_id,amount,status:"open",created_at,settled_at:null}`
- `GET /api/v1/questions/{id}/bounty`：公开；返回进行中悬赏，无悬赏 → `200 null`；问题不存在 → 404
- `GET /api/v1/users/me/points`：需登录（401）；返回 `{balance, entries: [{source, event_id, delta, reason, occurred_at}]}`；教师首次访问惰性开户并发放 100 初始分，学生只读既有余额与流水
- 资金流：发起时冻结积分；采纳时结算给答主；关闭或软删除且未采纳时全额退款（各只发生一次）
- 积分与声誉分离；教师初始额度 100 分，首版无充值/发放端点

## 四点十二、校园资料更新与邮箱验证（F10）

- `RegisterResponse`（`/register`、`/me`、`PATCH /me/profile` 共用）增量返回 `nickname`、`college`、`class_name`、`email_verified`（存量用户迁移后默认为 `false`）。
- `PATCH /api/v1/auth/me/profile`：需登录（401）；请求体 `nickname`（1–30 字，允许重名）、`college`（1–64 字）、`class_name`（1–64 字）均可选，至少传一项（空 `{}` → 422）；未传字段保持原值，显式传 `null` 清空，传空串/纯空白 → 422；成功返回 **200** + 更新后的 `RegisterResponse`。
- `POST /api/v1/auth/me/verify-email/send`：需登录（401）；成功 **204**（60s 冷却、15 分钟有效）；60s 内重发 → **429**；已验证用户 → **409**；Redis/SMTP 不可用或未配置 → **503**（自动回滚冷却与验证码，可立即重试）。
- `POST /api/v1/auth/me/verify-email/confirm`：需登录（401）；body `{"code": "6位ASCII数字"}`；成功或已验证 → **204**（幂等）；错码/过期/连续 5 次错码作废 → **400**（统一文案防枚举）；Redis 故障 → **503**。

## 四点十三、公开展示名与个人主页（F11）

- **展示名规则**：优先显示清洗后的 `nickname`；未设置昵称时按角色回退为 `管理员#<8位hex>`、`教师#<8位hex>`、`助教#<8位hex>`、`学生#<8位hex>`，未知角色回退 `用户#<8位hex>`（绝不暴露学号/工号/邮箱）；极端孤立缺失引用安全回退 `"未知用户"`。
- **增量回填字段**：
  - 问答与评论（`QuestionResponse`、`QuestionListItem`、`QuestionDetailResponse`、`AnswerResponse`、`CommentResponse`）均增量返回 `author_name`；
  - 排行榜条目（`LeaderboardEntryResponse`）增量返回 `display_name`（即使命中 60s 榜单缓存，展示名仍实时查询回填）；
  - 通知条目（`NotificationResponse`）增量返回 `actor_name`。
- `GET /api/v1/users/{user_id}/profile`：**公开**，无需登录；用户不存在 → **404**（detail `"用户不存在"`）；最小披露返回 `{user_id, role, display_name, nickname, college, class_name}`，严禁返回 `email`、`student_id`、`staff_id`、`email_verified` 等隐私字段。

## 四点十四、编辑回答（`PATCH /api/v1/answers/{answer_id}`，F12）

- 需登录（401）；**仅回答者本人**可编辑（非作者含提问者均 **403** `"仅回答者可编辑回答"`）。
- 请求体：`{"body": "1~5000字"}`（`extra=forbid`、`str_strip_whitespace=True`，纯空白/控制字符 → 422）。
- 回答不存在 → **404**；所属问题已关闭 → **409**；**已采纳回答**（所属问题必为 `open` 态）仍允许回答者本人编辑且保持 `is_accepted=true`。
- 成功返回 **200 + `AnswerResponse`**，包含最新净票数 `votes`、`author_name`、`is_teacher_verified`、`verified_by_name`、`verified_at` 与完整有序 `comments[]`（含每条评论作者的 `author_name`）。注：`votes` 与 `is_accepted` 为本次读取时快照，同瞬间并发投票或采纳时响应可能短暂滞后于库内最新状态（不影响正文写入），既有教师认证状态随正文编辑保留。

## 四点十五、软删除问题与回答（`DELETE /api/v1/questions/{question_id}`、`DELETE /api/v1/answers/{answer_id}`，F13）

- **认证与鉴权**：均需登录（401）；活跃内容下**鉴权 403 优先于业务冲突 409**（非提问者删问题 → **403** `"仅提问者可删除问题"`；非回答者删回答 → **403** `"仅回答者可删除回答"`）。
- **重复删除幂等与防泄露矩阵**：
  - `DELETE /api/v1/questions/{question_id}`：提问者首次删除 **204**；提问者重复删除仍 **204**（幂等，不重复退悬赏）；非作者对已删或不存在问题一律 **404**；已有采纳答案的问题不可删除 → **409** `"该问题已有采纳答案，不可删除"`；已关闭问题允许提问者删除（内容回收例外）。
  - `DELETE /api/v1/answers/{answer_id}`：回答者首次删除 **204**；父问题仍活跃时回答者重复删除仍 **204**；已采纳回答不可删除 → **409** `"已采纳的回答不可删除"`；已关闭问题下的未采纳回答允许回答者删除；非作者对已删回答、或**父问题已删时任意用户**均返回 **404**（绝不返回 403）。
- **悬赏联动**：软删除含未采纳开放悬赏的问题时，同事务全额退还冻结积分给发起教师（`bounty_refund`），重复删除不二次退款。
- **全链路可见性**：软删除后，对应问题/回答立即从列表（含无参/筛选/搜索/`total`）、详情、相关推荐、悬赏查询及徽章活跃统计中剔除，对其发起编辑/关闭/回答/投票/评论/采纳/悬赏一律返回 **404**。历史声誉流水、排行榜与站内通知不回滚/不回删（点击已删内容通知跳转 404）。

## 四点十六、评论二级回复（`POST /api/v1/questions/{id}/comments`、`POST /api/v1/answers/{id}/comments`，F14）

- **请求体（`CommentRequest`）**：`{"body": "1~5000字", "parent_id": "<uuid|null>"}`（保留 `extra=forbid`；`parent_id` 可缺省或 `null`，表示一级评论）。
- **响应形态（平铺，向后兼容）**：`CommentResponse` 增量返回可空 `parent_id: UUID | null`；`GET /api/v1/questions/{id}` 详情的 `comments[]` / `answers[].comments[]` 与 `PATCH /api/v1/answers/{id}` 的 `comments[]` 保持按 `created_at ASC, id ASC` **平铺有序返回**，由前端按 `parent_id` 分组展示二级缩进。
- **层级与校验口径**：
  - 严格两级树：允许回复同一宿主（问题或回答）下的一级评论（含回复自己的一级评论）；
  - 父评论不存在 → **404**（`detail: "评论不存在"`）；
  - 父评论的 `(target_type, target_id)` 与当前对象不一致（跨问题/跨回答/跨题答类型）→ **422**（`detail: "父评论不属于当前对象"`）；
  - 父评论自身已有 `parent_id`（试图发三级回复）→ **422**（`detail: "评论仅支持二级回复，不可回复二级评论"`）；
  - 所属问题已关闭 → **409**；所属问题或回答已软删除 → **404**（一二级评论随宿主软删除一同隐藏）。
- **通知联动（同事务写入，自操作均跳过）**：
  - 一级评论：沿用原有行为，向宿主作者发 `comment_created`；
  - 二级回复：① 若父评论作者 ≠ 回复者，向父评论作者发 `comment_replied`（`target_type="comment"`, `target_id=parent_comment.id`, `question_id=所属问题ID`）；② 若宿主作者 ≠ 回复者 且 宿主作者 ≠ 父评论作者，向宿主作者发 `comment_created`（同人去重只发 1 条 `comment_replied`）。

## 四点十七、RBAC 扩展与教师认证回答（F15）

- **角色与实时鉴权边界**：
  - 角色支持 `student` / `teacher` / `ta` / `admin`；
  - `POST /api/v1/auth/register` 保持**仅允许 `"student"` 与 `"teacher"`**，传 `"ta"` / `"admin"` 一律返回 **422**；
  - 受保护端点鉴权基于每次请求从 DB 实时读取的 `User.role`：管理员变更目标用户角色后，其既有 Access Token 在下次请求即按新角色生效/失效；
  - 角色变更保留原 `students.student_id` / `teachers.staff_id`，用户仍可用原学号/工号登录；
  - F07 教师悬赏 `POST /api/v1/questions/{id}/bounty` 保持**仅 `"teacher"`** 可发起（`student` / `ta` / `admin` 均返回 **403**）。
- **管理员用户管理（`require_roles("admin")`，未登录 401，非 `admin` 403）**：
  - `GET /api/v1/admin/users`：Query `page >= 1`（默认 1）、`page_size` 1~100（默认 20）、`role` 可选（`student`/`teacher`/`ta`/`admin`），按 `created_at DESC, id DESC` 排序；响应 `{items, total, page, page_size, total_pages}`，`AdminUserItem` 包含 `{id, role, email, student_id, staff_id, display_name, nickname, college, class_name, email_verified, created_at}`（绝不含 `password_hash`）；
  - `PATCH /api/v1/admin/users/{user_id}/role`：请求体 `{"role": "student"|"teacher"|"ta"|"admin"}`（`extra=forbid`）；不可修改本人角色 → **409**（`detail: "不可修改本人角色"`）；目标用户不存在 → **404**（`detail: "用户不存在"`）；幂等变更到同角色返回 **200 + `AdminUserItem`**。
- **教师/助教/管理员认证回答（`require_roles("teacher", "ta", "admin")`，未登录 401，学生 403）**：
  - `POST /api/v1/answers/{answer_id}/verify`：首次认证或幂等重复认证均返回 **200 + `AnswerResponse`**（包含真实 `votes`、`author_name`、`is_accepted`、`is_teacher_verified=true`、`verified_by_name`、`verified_at`、有序 `comments[]`）；重复认证保持首次认证人与认证时间不变；
  - `DELETE /api/v1/answers/{answer_id}/verify`：取消认证返回 **204**（未认证时同样幂等返回 **204**）；
  - 状态守卫：回答已软删或所属问题已软删 → **404**；所属问题已关闭 → **409**；
  - `AnswerResponse`（`GET /questions/{id}`、`POST /questions/{id}/answers`、`PATCH /answers/{id}`、`POST /answers/{id}/verify` 共用）：增量暴露 `is_teacher_verified`（默认 `false`）、`verified_by_name`（默认 `null`）、`verified_at`（默认 `null`）；
  - 通知与声誉联动：仅在首次变为已认证且 `answer.author_id != actor_id` 时同事务向答主写入 `answer_verified` 通知（`target_type="answer"`, `target_id=answer.id`, `question_id=question.id`）；重复认证、自操作、取消认证均不发通知；**不触发声誉变动**。

## 四点十八、课程上下文与选课（F16）

- **`GET /api/v1/courses`（公开，无需登录）**：
  - 分页 Query：`page >= 1`（默认 1）、`page_size` 1~100（默认 20）、可选 `semester`（空白串视为无筛选，非空须 2–32 字符且不含 `\t`/`\n`/`\r` 或控制字符，否则 **422**）。
  - 排序固定 `(created_at DESC, id DESC)`；`total` 与列表同口径；`total_pages = ceil(total / page_size)`（空库为 0）；批量回填 `teacher_name`。
- **`POST /api/v1/courses`（`require_roles("teacher", "admin")`，未登录 401，`student`/`ta` 403）**：
  - 请求体 `CreateCourseRequest`（`extra="forbid"`、`str_strip_whitespace=True`）：`code`（2–32 位，单源 `strip().upper()`，须符合 `^[A-Z0-9][A-Z0-9_-]{1,31}$`，如 `cs-se-301` 归一为 `CS-SE-301`）、`name`（2–100 字单行文本）、`semester`（2–32 字单行文本）。
  - 课程编号已存在（含大小写变体）→ **409**（`detail: "课程编号已存在"`）；成功返回 **201 + `CourseResponse`**。
- **`POST /api/v1/courses/{course_id}/enroll`（`require_roles("student")`，未登录 401，`teacher`/`ta`/`admin` 403）**：
  - 课程不存在 → **404**（`detail: "课程不存在"`）；重复选课 → **409**（`detail: "已选修该课程，请勿重复选课"`）；成功返回 **201 + `EnrollmentResponse`**。
- **`GET /api/v1/courses/{course_id}/students`（`require_roles("teacher", "ta", "admin")`，未登录 401，`student` 403）**：
  - 课程不存在 → **404**；按 `(enrolled_at ASC, id ASC)` 分页返回 `{items, total, page, page_size, total_pages}`。
  - `CourseStudentItem` 最小披露仅返回 `{student_id, student_name, enrolled_at}`（绝不暴露 `email`、学工号或密码哈希），`student_name` 随 F11 实时回填。

## 五、开发期调试入口

后端跑起来后直接开 **Swagger UI**：`http://localhost:<port>/docs`——交互式调试每个端点，与 `openapi.json` 同源生成。

**HEAD 请求注意**：当前框架对 GET 路由不自动支持 HEAD（连 `/health` 的 HEAD 都 405），探活/预检请统一用 GET。

## 六、前端消费指引

```bash
pnpm add -D openapi-typescript
pnpm add openapi-fetch
npx openapi-typescript ./openapi.json -o src/api/schema.d.ts
```

- 用 `openapi-fetch` 配合生成的 `schema.d.ts` 获得全链路类型；
- **不要用 `openapi-typescript-codegen`**（已停止维护）；
- 令牌格式：`Authorization: Bearer <access_token>`（登录/刷新响应中的 `access_token`，有效期 `expires_in` 秒）。
