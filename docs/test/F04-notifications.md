# F04 通知中心（基础）· 开发与测试台账

> 日期：2026-11-13 · 上下文：discovery（聚合/仓储/端点）+ qa（写入端口）+ identity（当前用户）· 依赖：无
> 裁定：D4 同步同事务 · D5 discovery 建骨架 · D6 `unique(type, source_event_id, recipient_id)` · D7 不设过期
> 分支/工作区：`feat/question-filter` 工作树（叠加 F02/F03/F05/F06 未提交改动），未 commit

## 一、交付范围

| 端点 | 语义 |
|:--|:--|
| `GET /api/v1/notifications` | 本人通知分页（`page/page_size/unread_only`），新→旧 |
| `GET /api/v1/notifications/unread-count` | 本人未读数 |
| `POST /api/v1/notifications/{id}/read` | 单条已读，幂等 204；非本人/不存在 404 |
| `POST /api/v1/notifications/read-all` | 全部已读，返回本次更新条数 |

三类通知（自己操作自己的内容不通知）：
- 我的问题有新回答（收件人=提问者，actor=回答者，source_event=answer_id）
- 我的回答被采纳（收件人=答主，actor=采纳者，source_event=采纳事件 id）
- 我的问题/回答有新评论（收件人=宿主作者，actor=评论者，source_event=comment_id）

明确不做：@提醒（F21）、邮件/推送、通知偏好、保留期过期清理、前端通知页。

## 二、六步法改动清单

| 步骤 | 文件 | 改动 |
|:--|:--|:--|
| 1 domain | `discovery/domain/notification.py`、`repository.py` | 通知聚合/类型/目标枚举、`build_notification`；仓储端口（add/list/mark_read/mark_all/unread_count） |
| 2 application | `discovery/application/*` | 列表分页、单条/全部已读、未读数四个只读/写用例 |
| 3 infrastructure | `discovery/infrastructure/models.py`、`notification_repository.py`、`notification_writer.py` | `notifications` 表 + 两个索引；`ON CONFLICT DO NOTHING` 幂等写入；分页/已读 SQL |
| 4 interfaces | `discovery/interfaces/api/*`、`main.py` | 四端点 + 白名单 schema + 组合根；路由注入当前用户 |
| 5 tests | 见第四节 | qa 钩子 6 / discovery 用例 5 / 仓储集成 4 / API 集成 1（全链路） |
| 6 收口 | 迁移 + 契约 + 文档 | `alembic revision --autogenerate` 生成 `82908edc9ebf`（**未 upgrade，等人工审核**）；`openapi.json` 重导出 24 paths/26 ops；台账/PROGRESS |

### qa 侧接线（D5 修正版，遵守护栏）

- qa `application/ports.py` 定义 `NotificationWriter` Protocol（原始类型签名），qa 用例只依赖该端口；
- discovery `infrastructure/notification_writer.py` 结构化实现，**零 import qa**；
- discovery `interfaces/api/deps.py` 暴露 `get_notification_writer(session)`；
- qa `interfaces/api/deps.py` 只 import discovery interfaces 工厂（interfaces→interfaces 合法）；
- 同一 `AsyncSession` → 通知与业务同事务提交；写入失败整体回滚（首版有意的强一致取舍）。

### 关键设计

- **幂等**：库级 `(type, source_event_id, recipient_id)` 唯一 + `ON CONFLICT DO NOTHING`；重复事件/并发双投递恰一行。
- **收件人隔离**：所有端点收件人恒取令牌；标记他人通知返回 404（不泄露存在性）。
- **已读幂等**：单条已读用无条件 `UPDATE ... RETURNING`（归属正确即 204，重复调用仍 204）；全部已读按"未读→已读"计数。

## 三、门禁实测（2026-11-13，定向）

| 门禁 | 命令 | 结果 |
|:--|:--|:--|
| Lint | `ruff check .` | All checks passed（0） |
| 类型 | `mypy app` | 0 errors（**125 文件**） |
| 单元（CI 口径） | `pytest -m "not integration" -q` | **276 passed**（168 deselected） |
| 契约导出 | `scripts/export_openapi.py` | **24 paths / 26 operations** |
| 迁移 | `alembic revision --autogenerate` | 生成 `82908edc9ebf_add_notifications_table_f04.py`；**已审核并 apply（2026-11-13）** |
| 全量（含 integration） | `pytest -q` | **457 passed**（195.90s，F03–F07 全量） |

## 四、测试覆盖

| 文件 | 条数 | 覆盖点 |
|:--|:--|:--|
| `tests/contexts/qa/application/test_notification_hooks.py` | 6 | 新回答通知提问者；自答不通知；题目评论/答评收件人；自评不通知；采纳通知答主且 source_event=事件 id；自采纳不通知 |
| `tests/contexts/discovery/application/test_notification_use_cases.py` | 5 | 分页/未读筛选；收件人隔离；单条已读归属；全部已读计数幂等；未读数 |
| `tests/contexts/discovery/infrastructure/test_notification_repository.py` | 4 | 唯一键幂等；倒序/分页/未读；已读归属与幂等；全部已读计数 |
| `tests/contexts/discovery/interfaces/test_notification_api.py` | 1 | 全链路：回答/评论/采纳三类触发、自操作不通知、列表顺序、未读数、单条已读幂等、他人 404、read-all、401 |

## 五、DoD 勾选

- [x] 六步法落地，仅触及本 Fxx 点名对象
- [x] 迁移已人工审核并应用：`82908edc9ebf`（2026-11-13）
- [x] 单元 + 集成测试已写入
- [x] `openapi.json` 重导出
- [x] 本台账登记
- [x] `docs/PROGRESS.md` 变更记录登记
- [x] 定向门禁全绿（ruff / mypy / 276 单测）
- [x] 全量 pytest：**457 passed**（195.90s）
- [x] 未执行任何 commit/push

## 六、2026-11-17 Bug 修复：通知补齐 `question_id`（零迁移）

- **修复内容**：复用既有 `NotificationModel.payload`（JSONB），为 `NotificationWriter.write()` / `Notification` / `NotificationResponse` 增加可选 `question_id: UUID | None = None`；qa 侧回答、问题评论、回答评论、采纳四类写入全部传入所属 `question_id`，仓储 `_to_domain()` 对空或非字符串值做防御性降级返回 `None`。
- **测试同步**：
  - `test_notification_hooks.py`：4 类写入均断言 `question_id`；
  - `test_notification_repository.py`：新增 `test_question_id_payload_roundtrip_and_missing_defaults_none`；
  - `test_notification_api.py`：新增回答评论触发并校验三类通知响应均含 `question_id`。
- **实测门禁**：单测口径全绿（288 passed / 82.90% / domain 94% / ruff 0 / mypy 134 文件 0）；集成 **180 passed**（249.89s），全量 **468 passed**（254.62s）。补充环境：临时 Redis 容器使用随机宿主端口 1779（6379/6393 落入 Windows 保留段），数据库迁移已在 head `29caa98ef40a`。
