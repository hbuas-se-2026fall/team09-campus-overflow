# F01 问题筛选（US-Q07）· 开发与测试台账

> 日期：2026-11-05 · 上下文：qa · 依赖：无
> 裁定：D0=A（归属修订为 qa）· D1 不传=全部 · D2 闭区间+逆序 422+必须带时区 · D3a 重复参数 `?tag=a&tag=b` · D3b AND · D4 按 `Tag.key` 匹配 · D5 首版不加索引
> 分支/工作区：main 工作树（叠加上一轮前端测试未提交改动），未 commit

## 一、交付范围

`GET /api/v1/questions` 新增四个可选筛选参数，空条件与 F01 之前行为完全一致：

| 参数 | 形式 | 语义 |
|:--|:--|:--|
| `tag` | 可重复 `?tag=a&tag=b` | 多标签 **AND**；按 `Tag.key` 匹配（小写 + ς→σ 折叠），同名去重 |
| `status` | `open` / `closed` | 省略 = 全部（D1，向后兼容） |
| `created_from` / `created_to` | ISO8601，必须带时区 | 闭区间；naive / 逆序 / 非法格式 → 422 |

明确不做：关键词检索（F02）、按课程筛选（F17）、前端筛选栏。

## 二、六步法改动清单

| 步骤 | 文件 | 改动 |
|:--|:--|:--|
| 1 domain | `app/contexts/qa/domain/repository.py` | 新增 `QuestionFilter`（校验+归一集中在 `__post_init__`，抛 `DomainValidationError`）；`QuestionRepository.list_paginated` 增可选 `filters` |
| 2 application | `app/contexts/qa/application/queries.py`、`list_questions_use_case.py` | `ListQuestionsQuery` + `filters`；用例透传，不解释条件 |
| 3 infrastructure | `app/contexts/qa/infrastructure/question_repository.py` | 新增 `_apply_filters(stmt, filters)` 单一谓词源，**COUNT 与分页 SELECT 共用**；多标签逐 key `EXISTS`（AND），`sort=votes` 继续复用 `_question_net_votes()` |
| 4 interfaces | `app/contexts/qa/interfaces/api/questions.py` | 声明 `tag: list[str] \| None`、`status`（alias）、`created_from/to`；路由只组装 filter，**零新增 try/except、零校验分支** |
| 5 tests | 见第四节 | domain 10 条、用例 1 条、仓储集成 1 条、API 集成 5 条；fake 签名同步 |
| 6 门禁 | 见第三节 | ruff / mypy / coverage / 契约 / 全量 pytest |

### 关键设计

- **total 同口径**：原实现 `COUNT` 统计整表、分页 SELECT 无 WHERE（A0-4 隐患）；现两者都经 `_apply_filters` 套用同一组谓词。
- **校验位置**（用户修正 1）：逆序、naive 时区、空/非法 tag 全部在 domain 抛 `DomainValidationError`，经 C2 全局映射落 422；路由无新增校验代码。
- **多 tag 去重**（用户修正 2）：`QuestionFilter` 先把原始显示名经 `Tag(raw)` 校验并转 `key`，按 key 去重；仓储对每个 key 一个独立 `EXISTS`。

## 三、门禁实测（2026-11-05）

| 门禁 | 命令 | 结果 |
|:--|:--|:--|
| Lint | `ruff check .` | All checks passed（0） |
| 类型 | `mypy app` | 0 errors（100 文件） |
| 单元（CI 口径） | `pytest -m "not integration" --cov=app --cov-fail-under=70` | **215 passed**（+11），TOTAL **83.25%**（2095 语句 / 351 未覆盖） |
| 核心聚合 | `coverage report --include="*/domain/*" --fail-under=90` | **95%**（468 语句 / 22 未覆盖） |
| 契约导出 | `scripts/export_openapi.py` + `--check` | 一致（**17 paths / 19 operations** 未变，仅参数扩展） |
| 全量（含 integration） | `pytest -q` | **343 passed**（176.96s；+17：domain 10 + 用例 1 + 仓储 1 + API 5） |

## 四、测试覆盖

### 4.1 新增用例

| 文件 | 条数 | 覆盖点 |
|:--|:--|:--|
| `tests/contexts/qa/domain/test_question_filter.py` | 10 | 空条件默认值、tag 归一/去重（大小写与 ς→σ）、strip、naive from/to、逆序、等值边界、空 tag、非法字符、status 保留 |
| `tests/contexts/qa/application/test_question_query_use_cases.py` | +1 | 用例把 `filters` 原样透传给仓储 |
| `tests/contexts/qa/infrastructure/test_question_repository.py` | +1 | 时间闭区间：[base, base+1s] 命中边界两行、排除 ±2s 两行，且 `total == 结果数` |
| `tests/contexts/qa/interfaces/test_question_api.py` | +5 | 多 tag AND + 大小写不敏感 + 重复传参去重；status 单条件 + 不传=全部 + `sort=votes` 组合；时间窗口内外；5 类非法参数 422 且不回显；筛选分页 total/切片严格对账 |

### 4.2 测试矩阵要点

- **标签**：`React` + `TypeScript` → 仅同时持有两者的问题命中；仅 `React` 或仅 `PostgreSQL` 不命中；`react`/`REACT` 与 `React` 等价；`?tag=react&tag=REACT` 去重不报错。
- **状态**：创建并关闭后，`status=closed` 命中、`status=open` 排除；不传 status 时关闭问题仍在（向后兼容）。
- **时间**：窗口 `[now−1min, now+1min]` 命中新帖；`created_from=now+1h` 不命中；`[t, t]` 单点窗口合法。
- **非法输入**：`status=bogus`、`tag=`（空串）、naive `created_from`、逆序区间、`created_to=not-a-date` 全部 422，响应不回显输入。
- **分页对账**：三标签 AND 共 3 帖，`total_pages=ceil(total/page_size)`，第 1/2 页 `total` 一致、跨页无重复、3 帖落在前两页。

### 4.3 本轮发现的缺陷（测试自身，非产品）

- 时间区间用例首版断言 `total == 2`，在第二轮全量运行中失败（窗口内累积了上一轮种子，实际 4）。根因：用例跨轮非幂等，依赖 2001 年窗口为空。修正为**成员断言 + `total == len(items)` 同口径断言**，不假设窗口无历史数据。产品代码零改动。

## 五、索引评估（D5 结论：首版不加，无迁移）

| 筛选 | 现有索引 | 结论 |
|:--|:--|:--|
| `status` | 无 | status 仅 open/closed 低基数，过滤选择性差，建索引收益低；暂不加 |
| `tag` | `ix_question_tags_tag(tag_id)` + `uq_tags_key(key)` | EXISTS 走 tag_id 反查与 key 唯一索引，现有索引足够 |
| 时间 | `questions.created_at` 已索引 | 现有索引可用 |

因此 **不产生 Alembic 迁移**，`alembic upgrade head` 未执行。

## 六、DoD 勾选

- [x] 六步法落地，仅触及本 Fxx 点名对象
- [x] 无表结构变更，无需迁移
- [x] 单元 + 集成测试写入 `tests/`
- [x] `openapi.json` 重导出且 `--check` 一致
- [x] 本台账登记
- [x] `docs/PROGRESS.md` 变更记录登记
- [x] 门禁：ruff 0 / mypy 0 / coverage 83.25%（≥70%）/ domain 95%（≥90%）/ 全量 343 passed
- [x] 未执行任何 commit/push

## 七、文档同步（D0=A）

- `docs/domain/context-map.md`：Q07 从 discovery 改为 qa 归属，新增 2026-11-05 复核裁定注记
- `docs/sprint/product-backlog.md`：新增 2026-11-05 注记，不改写 2026-10-08 历史行；明确 **US-Q07 部分交付**（关键词留 F02）
- `docs/api/api-contract-notes.md`：分页契约补筛选参数与 422 口径
- `docs/PROGRESS.md`：变更记录新增本 Fxx 行

## 八、遗留

- US-Q07 的**关键词检索**由 F02 收口；按课程筛选由 F17（依赖 F16）。
- 测试数据：本轮集成用例创建了真实技术内容的问题（React/TypeScript/PostgreSQL 标签），按项目数据纪律保留；不生成占位或随机字符串标题。
