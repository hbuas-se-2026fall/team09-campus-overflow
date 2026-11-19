# F10 校园资料扩展与邮箱验证 · 开发与测试台账

> 日期：2026-11-18 · 上下文：`identity` + `shared`（`UNSET` 哨兵）· 依赖：F09 单 SQL 查询骨架
> 裁定：D1 `UNSET` 归 `app/shared/sentinel.py`（守 A1）· D2 `User` 持 `Nickname`/`College`/`ClassName` VO，允许昵称重名，验证码仅 ASCII `^[0-9]{6}$` · D3 `PATCH /api/v1/auth/me/profile` 返回 `200 + RegisterResponse`，`model_fields_set` 区分未传与显式 `null`，空 `{}` 422 · D4 `send`（204 / 409 / 429 / 503），`confirm`（幂等 204 / 统一 400 / 503）；`EmailVerificationUnavailableError` 直接继承 `Exception` · D5 `EmailVerificationStore` 无 `consume` · D6 方案 A：`with_for_update(of=UserModel)` + `populate_existing=True` + 独立定向 UPDATE 防 lost update + 不做事务内删码靠 900s TTL · D7 `app_env` 解耦 `debug`，`prod` 强制完整 SMTP 与非默认 HMAC · D8 存量用户 `email_verified=False`
> 分支/工作区：`feat/f10-profile-and-email-verify`（F10 改动暂未 commit）

## 一、交付范围

| 端点 | 语义 |
|:--|:--|
| `PATCH /api/v1/auth/me/profile` | 登录态局部更新 `nickname`（1–30 字，允许重名）/ `college`（1–64 字）/ `class_name`（1–64 字）；未传字段保留、显式 `null` 清空、空体 `{}` 422；成功返回 `200 + RegisterResponse` |
| `POST /api/v1/auth/me/verify-email/send` | 生成 6 位安全随机码并发送；成功 `204`；已验证 `409`；60s 冷却 `429`；Redis/SMTP 未配或失败 `503`（Lua compare-and-delete 按 `send_token` 同时回滚冷却与验证码） |
| `POST /api/v1/auth/me/verify-email/confirm` | 验证 6 位 ASCII 数字码；成功或已验证 `204`（行锁幂等）；错码/过期/满 5 次作废统一 `400`；Redis 不可用 `503` |
| `POST /register` & `GET /me` | `RegisterResponse` 增量补齐 `nickname`、`college`、`class_name`、`email_verified` |

明确不做：更换绑定邮箱、引入第三方邮件依赖、限制未验证邮箱用户的提问/回答/投票权限、前端 UI。

## 二、六步法改动清单

| 步骤 | 文件 | 改动 |
|:--|:--|:--|
| 0 共享/配置 | `app/shared/sentinel.py`、`app/config/settings.py`、`.env.example`、`app/main.py` | 新增 `UNSET` 哨兵；`Settings` 增 `app_env`、`email_verify_hmac_secret` 与 `smtp_*`；`app_env=prod` 默认 HMAC 启动 fail-fast |
| 1 domain | `app/contexts/identity/domain/value_objects.py`、`errors.py`、`user.py`、`repository.py` | 新增 `Nickname`/`College`/`ClassName`/`VerificationCode`；4 个错误类；`User` 持 VO 与 `update_profile`/`mark_email_verified`；`get_by_id(..., *, for_update: bool = False)`、`update_profile`、`mark_email_verified` |
| 2 application | `app/contexts/identity/application/commands.py`、`ports.py`、3 个新用例文件 | `UpdateProfileCommand`/`SendEmailVerificationCommand`/`ConfirmEmailVerificationCommand`；`VerificationResult`、`EmailVerificationStore`、`VerificationCodeSender`；3 个用例（无 `consume`） |
| 3 infrastructure | `app/contexts/identity/infrastructure/models.py`、`repository.py`、`email_verification_store.py`、`email_sender.py`、`alembic/versions/c451483b0660_*.py` | `users` 增 4 列（`email_verified` `server_default=false()`）；`with_for_update(of=UserModel)` + `populate_existing=True` + 两条定向 `UPDATE`；Redis HMAC + 3 条 Lua 脚本；SMTP 线程池超时适配器 + `app_env` 工厂 |
| 4 interfaces | `app/contexts/identity/interfaces/api/schemas.py`、`error_mapping.py`、`deps.py`、`routes.py` | `RegisterResponse`、`UpdateProfileRequest`（`model_fields_set`）、`ConfirmEmailVerificationRequest`；409/429/400/503 映射；3 个端点与组合根 |
| 5 tests | 领域/应用/适配器单测 + API 集成测试 + 契约/桩同步 | 单测 +18、集成 +6，全库运行 `316 passed / 190 passed = 506 passed` |
| 6 收口 | `openapi.json`、`tests/test_contract.py`、本台账、`docs/api/api-contract-notes.md`、`docs/PROGRESS.md`、`README.md` | 契约升至 `29 paths / 32 ops`，文档与门禁全数登记 |

### 关键设计

- **外连接行锁写法**：[repository.py](../../app/contexts/identity/infrastructure/repository.py) 在 `_user_select()` 上使用 `.with_for_update(of=UserModel).execution_options(populate_existing=True)`，避开 PG 禁止对外连接可空侧加 `FOR UPDATE` 的限制，同时消除同会话 `CurrentUser` identity map 旧值。
- **并发与跨存储顺序**：`confirm` 先对 `users` 行加锁，已验证直接 204，未验证才 `store.verify()` 再定向 `mark_email_verified()`，不在事务内提前删码（防 commit 失败丢码，靠 900s TTL 自然过期）。
- **发信回滚并发隔离**：`email_verify:cd:{id}` 与 `email_verify:code:{id}` 绑定同一次 `send_token`，发信异常通过 Lua compare-and-delete 同时回滚自己，绝不误删并发新请求写入的新码。

## 三、门禁实测（2026-11-18）

| 门禁 | 命令 | 结果 |
|:--|:--|:--|
| Lint | `ruff check .` | `All checks passed!` |
| 类型 | `mypy app` | `Success: no issues found in 141 source files` |
| 单元 + 总覆盖率 | `pytest -m "not integration" --cov=app --cov-report=term-missing --cov-fail-under=70 -q` | **316 passed**, 190 deselected；TOTAL **83.66%** |
| 核心聚合覆盖率 | `python -m coverage report --include="*/domain/*" --fail-under=90` | **94%** |
| 契约防漂移 | `python scripts/export_openapi.py --check` | `openapi.json 与当前代码一致`（**29 paths / 32 operations**） |
| 架构 + 契约测试 | `pytest tests/test_architecture.py tests/test_contract.py -v` | **15 passed** |
| 全量集成 | `pytest -m integration -q` | **190 passed**, 316 deselected（215.66s） |
| 迁移往返 | `alembic upgrade head` → `alembic downgrade ef84c7f8187e` → `alembic upgrade head` → `alembic current` | `ef84c7f8187e` → `c451483b0660` → `ef84c7f8187e` → `c451483b0660 (head)` |
| 迁移漂移 | `alembic check` | `No new upgrade operations detected.` |
| 存量回填核验 | `psql`: `SELECT count(*), count(*) FILTER (WHERE email_verified) FROM users` | `total_users=4938`、`verified_users=2`（其余 4,936 条存量行均为 `false`） |

## 四、测试覆盖

| 文件 | 条数 | 覆盖点 |
|:--|:--|:--|
| `tests/contexts/identity/domain/test_user.py` | +3 | `Nickname`/`College`/`ClassName` trim 与上限、`VerificationCode` 拒 Unicode 数字、`User.update_profile`/`mark_email_verified` |
| `tests/contexts/identity/application/test_profile_and_email_verify_use_cases.py` | 8（新建） | 局部更新与显式 `None` 清空、空请求/缺失用户、`send` 409/429/失败回滚、`confirm` 行锁幂等与统一 400 |
| `tests/contexts/identity/infrastructure/test_email_verification_adapters.py` | 7（新建） | Redis 只存 HMAC、5 次错码作废、compare-and-delete 不删新码、`RedisError→503`、`app_env` 与半套 SMTP 判据、SMTP timeout/异常、prod 默认 HMAC 启动 fail-fast、503 不被 422 吞掉 |
| `tests/contexts/identity/interfaces/test_profile_and_email_verify_api.py` | 6（新建集成） | PATCH 部分更新/`null`/空体 422/重名；并发 5×send（1×204 + 4×429）与 HMAC 落盘；并发双 `confirm` 204/204 + 与 PATCH 并发无 lost update；过期与 5 次错码作废；SMTP 失败回滚与 prod 未配 503；Redis 故障 503 |

## 五、DoD 勾选

- [x] 六步法落地，`test_architecture.py` 全绿（`UNSET` 放 `shared`，无 A1/A8 违规）
- [x] 迁移 `c451483b0660` 已审阅并通过 `down → up` 往返及 `alembic check` 零漂移校验
- [x] 单元（+18）与真实 PG+Redis 并发集成（+6）实测全绿（总 506 passed）
- [x] `openapi.json`（29 paths / 32 ops）与 `tests/test_contract.py` 已同步且过 `--check`
- [x] 本台账、`docs/api/api-contract-notes.md`、`docs/PROGRESS.md`、`README.md` 已登记
- [x] 本地六道门禁 + 架构/契约测试全绿
