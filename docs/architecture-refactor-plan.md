# JobPicky 架构解耦重构计划（历史实施资料）

> 本文记录历史计划，不再代表当前架构。当前代码结构、职责和调用链以 [`architecture.md`](architecture.md) 为准。

状态：计划基线，尚未开始实施

## 1. 目标和范围

JobPicky 的核心目标是让岗位数据、匹配、推荐和本地数据库完全独立于本地 WebUI 与飞书。

目标依赖方向：

```text
Web / CLI
    ↓
公共应用服务
    ↓
岗位抓取 → 岗位写入 → 匹配 → 推荐 → 本地数据库
                                      ↓
                         可选：飞书回拉、推送、通知
```

面向用户的入口保持为：

```text
jobpicky init
jobpicky daily
jobpicky web
```

入口内部可以重写，但不能改变用户可完成的任务。

本计划明确采用“干净重建”策略：当前没有真实用户数据，不维护旧内部接口，也不做旧运行数据库迁移。

## 2. 当前调查结论

当前源码和测试基线：

- 当前测试基线为 `235 passed`。
- 运行数据库是单一的 `jobs.sqlite`。
- 打包 seed 位于 `src/jobpicky/resources/jobs_seed.sqlite`，包含 747 条岗位。
- `jobs`、`job_matches`、`recommended_jobs`、`job_user_state`、`scan_runs`、`feishu_sync` 已经覆盖目标数据类别。
- 主要问题是流程编排和依赖方向，不是必须保留旧数据库格式。

主要职责问题：

| 文件和函数 | 当前问题 |
| --- | --- |
| `src/jobpicky/services/scanning.py::run_daily_workflow()` | 加锁、飞书回拉、抓取、写入、匹配、推荐、官网补全、飞书同步、通知和结果记录全部集中在一个函数。 |
| `src/jobpicky/services/initialization.py::InitializationService.initialize()` | 把本地 seed/schema、全量匹配、工作台创建和首次同步混为一个初始化流程。 |
| `src/jobpicky/web/app.py::TaskManager._run_local()` | Web 后台任务直接恢复 seed、重匹配并启动每日扫描。 |
| `src/jobpicky/pipeline.py` | `run_daily_with_jobs()`、`rematch_existing_jobs()`、`run_init_with_page_batches()` 和详情回填重复实现岗位写入、匹配和推荐。 |
| `src/jobpicky/storage.py::JobRepository` | schema、迁移、岗位、匹配、推荐、用户状态、扫描和飞书同步全部由同一类负责。 |
| `src/jobpicky/cli.py` | CLI 自己实现初始化、重匹配、飞书同步和导出流程，没有完全复用 Web 的应用服务。 |
| `src/jobpicky/pipeline.py` → `src/jobpicky/audit.py` | 核心 pipeline 直接依赖飞书用户状态回拉。 |
| `src/jobpicky/services/scanning.py` → `src/jobpicky/feishu.py` | `skip_feishu` 同时控制回拉、官网补全、推送和通知。 |

必须保留的业务语义：

- 岗位标准化和去重规则不变。
- 每日更新只处理新增或变化岗位。
- 全量重匹配可以重建推荐集合。
- 每日推荐追加与全量推荐重建是两种不同语义。
- 本地处理完成后，飞书失败不能破坏本地结果。
- 用户状态、备注和未知飞书状态不能被岗位同步覆盖。
- 错误信息必须继续脱敏。
- 运行锁和取消行为继续有效。

## 当前关键调用链摘要

以下调用链根据当前源码和测试整理，仅用于定位待替换代码，不代表必须保留旧内部接口。Web 和 CLI 的差异也保留在摘要中，避免后续阶段把它们误认为同一个旧用例。

### 首次本地使用（Web）

```text
POST /api/local/start
→ web.app 路由加载并校验本地配置
→ TaskManager.start_local()
→ TaskManager._run_local()
→ restore_seed_database(paths.database)
→ JobRepository.init_schema()
→ rematch_existing_jobs(repo, config)
    → list_stored_jobs()
    → _job_from_row()
    → Matcher.match()
    → save_match()
    → sync_global_recommendations()
→ run_daily_workflow(..., skip_feishu=True)
    → JobRepository.init_schema()
    → DailyRunGuard
    → WonderCVCrawler.crawl(mode="daily", should_stop=...)
        → parse_wondercv_list()
        → parse_wondercv_detail()
    → run_daily_with_jobs()
        → upsert_job()
        → Matcher.match()
        → save_match()
        → append_recommendations()
    → vacuum()
    → record_scan_run()
    → RunReport
→ Web 轮询 /api/tasks/{task_id}
→ GET /api/jobs
→ WebStateService.jobs()
```

问题：

- Web 层直接编排 seed、数据库初始化、全量匹配和每日扫描。
- 首次使用先全量重匹配，随后每日扫描可能再次匹配。
- `skip_feishu=True` 还会影响官网 URL 补全和通知，不只表示“不推送飞书”。
- `WebStateService.health()`、`InitializationService.preview()` 或提前调用岗位查询可能先创建空 schema，使后续 seed 恢复被“目标文件已存在”判断跳过；这是阶段 1/2 必须明确处理的首次使用问题。

### 首次连接飞书（Web）

```text
POST /api/feishu/test
→ load_config()/读取 profile
→ validate_config() 和请求参数校验
→ 使用提交凭据构造 test_config
→ FeishuConfig.from_config(test_config)
→ FeishuBitableClient.get_app()
→ WebStateService.save_feishu_credentials()
   （仅在连接测试成功后保存凭据）
→ InitializationService.initialize(test_config, client=client)
    → validate_config(require_feishu=True)
    → restore_seed_database(paths.database)
    → JobRepository.init_schema()
    → WorkspaceProvisioner.provision()
        → 回调保存 workspace_table_id
        → 保存 workspace schema 版本
    → rematch_existing_jobs(repo, config)
    → sync_feishu(repo, config,
                  repo.list_feishu_reconciliation_rows())
```

CLI 的首次初始化不是这条链，而是 `cli._run_init()` 自己完成：

```text
收集并保存配置
→ restore_seed_database()
→ JobRepository.init_schema()
→ 飞书只读预检
→ 用户确认
→ WorkspaceProvisioner.provision()
→ rematch_existing_jobs()
→ _sync_feishu()
→ Excel 导出、scan_runs、report、vacuum
```

问题：

- Web 的“测试连接”实际还负责保存凭据、创建工作台、重匹配和首次同步。
- 本地 seed 初始化与飞书连接耦合。
- Web 与 CLI 的工作台预检、确认和失败边界不一致。

### 本地每日更新

CLI 的纯本地每日更新是：

```text
CLI daily --no-feishu
→ cli._run_daily()
→ run_daily_workflow(skip_feishu=True)
→ JobRepository.init_schema()
→ DailyRunGuard
→ WonderCVCrawler.crawl()
→ run_daily_with_jobs()
    → upsert_job()
    → Matcher.match()
    → save_match()
    → append_recommendations()
→ scan_runs / report / vacuum
```

Web 的“本地扫描”并不是同一个入口：

```text
POST /api/local/start
→ seed 恢复
→ 全量 rematch_existing_jobs()
→ run_daily_workflow(skip_feishu=True)
```

问题：

- Web 本地扫描包含首次本地初始化和全量重匹配，CLI daily 则是纯每日增量更新。
- 两者没有一个明确的公共“本地使用”与“每日更新”用例边界。
- `skip_feishu` 同时控制飞书分支、官网链接补全和通知。

### 飞书每日更新

Web `/api/tasks/daily` 和 CLI `daily` 最终都调用 `run_daily_workflow()`：

```text
run_daily_workflow()
→ _feishu_is_configured()
→ DailyRunGuard
→ FeishuBitableClient.list_all_records()
→ pull_user_states_from_feishu()
    → audit.recover_user_states()
    → update_user_state() / mark_sync()
→ WonderCVCrawler.crawl()
→ run_daily_with_jobs()
    → upsert_job()
    → Matcher.match()
    → save_match()
    → append_recommendations()
→ _notification_rows()
→ OfficialUrlFinder()
→ enrich_official_urls(..., only_recommended=True)
→ sync_feishu(list_feishu_sync_candidates())
→ FeishuBot.send_text(build_daily_message(...))
→ vacuum()
→ record_scan_run()
→ RunReport
```

当前测试锁定的关键行为是：飞书用户状态回拉失败或出现异常时，后续飞书推送应被阻止，但本地岗位处理结果不能被回滚；结果字段、退出码和错误脱敏以 `tests/test_daily_workflow.py` 为准。

问题：

- 本地核心更新、飞书状态回拉、官网补全、飞书推送和通知集中在一个函数。
- 每日流程使用 `list_feishu_sync_candidates()`，初始化和 CLI 重匹配使用 `list_feishu_reconciliation_rows()`，旧远端记录的处理范围不一致。
- 飞书失败和本地成功状态没有独立的应用结果边界。

### 重点替换位置

- `src/jobpicky/services/scanning.py::run_daily_workflow()`
- `src/jobpicky/services/initialization.py::InitializationService.initialize()`
- `src/jobpicky/web/app.py::TaskManager._run_local()`
- `src/jobpicky/web/app.py::TaskManager._run_daily()`
- `src/jobpicky/pipeline.py::run_daily_with_jobs()`
- `src/jobpicky/pipeline.py::rematch_existing_jobs()`
- `src/jobpicky/cli.py::_run_init()`
- `src/jobpicky/cli.py::_run_daily()`
- `src/jobpicky/web/app.py` 中的 `/api/feishu/test` 路由

## 3. 新数据库和 seed 策略

不做旧运行数据库迁移。

### 3.1 权威岗位源数据

第一阶段将现有 747 条岗位从旧 seed SQLite 导出为：

```text
src/jobpicky/resources/jobs_seed_source.json
```

JSON 是岗位 seed 的权威源文件，记录导入所需的原始岗位字段。新的 SQLite 只是由 JSON 生成的运行时 seed，不再作为唯一数据源。

建议保留两个脚本：

```text
scripts/export_seed_source.py   # 一次性或需要时从旧 seed 导出 JSON
scripts/build_seed.py            # 从 JSON 创建 jobs_seed.sqlite
```

### 3.2 新 seed 数据库

使用当前数据库的业务含义重新生成：

```text
src/jobpicky/resources/jobs_seed.sqlite
```

当前表结构原则上保持岗位、匹配、推荐、用户状态、扫描和飞书同步这几个业务类别。只有明确阻碍核心服务的字段或表才调整，不在阶段 1 顺手做字段重设计。新 seed 至少包含：

- 岗位主数据表；
- 匹配结果表；
- 推荐记录表；
- 用户求职状态表；
- 扫描记录表；
- 飞书同步状态表。

开发环境的旧运行数据库直接删除并由新 seed 重建。旧数据库不参与新代码运行，也不需要 schema 版本、迁移、回滚或兼容读取。旧迁移实现不移植到新架构；确认没有新代码依赖后再删除。

## 4. 目标核心服务

建议新增 `src/jobpicky/core/`，核心服务不导入飞书、Web 或 CLI。

```text
src/jobpicky/core/
├── bootstrap.py
├── ingestion.py
├── matching.py
├── recommendations.py
├── daily_update.py
└── queries.py
```

### `DatabaseBootstrapService`

文件：`src/jobpicky/core/bootstrap.py`

职责：

- 创建运行数据库目录；
- 从 `jobs_seed_source.json` 或生成好的 seed 加载 747 条岗位；
- 创建新 schema；
- 提供数据库初始化结果。

不负责：飞书、用户匹配配置、Web 任务、通知。

### `JobIngestionService`

文件：`src/jobpicky/core/ingestion.py`

职责：

- 接收源适配器产生的岗位；
- 执行标准化、去重和增量写入；
- 区分新增、变化和未变化岗位；
- 保留详情字段保护规则。

WonderCV 的 HTML 解析和网络抓取仍放在 `src/jobpicky/wondercv.py`，它只是岗位源适配器。

### `MatchingService`

文件：`src/jobpicky/core/matching.py`

职责：

- 对指定岗位或全部岗位调用 `Matcher.match()`；
- 保存匹配结果；
- 返回匹配结果供推荐服务使用。

不负责抓取、推荐和飞书同步。

### `RecommendationService`

文件：`src/jobpicky/core/recommendations.py`

职责：

- 根据匹配结果追加每日推荐；
- 执行全量推荐重建；
- 明确区分每日追加和全量重建；
- 保持推荐幂等性。

### `DailyUpdateService`

文件：`src/jobpicky/core/daily_update.py`

唯一流程：

```text
抓取 → JobIngestionService → MatchingService → RecommendationService
```

不负责：飞书客户端、机器人通知、Web 后台任务、运行锁和页面序列化。

### `JobQueryService`

文件：`src/jobpicky/core/queries.py`

职责：

- 查询岗位、推荐岗位和统计数据；
- 为 Web、CLI 和飞书适配层提供统一结果；
- 隐藏跨表 SQL 和数据库字段布局。

初期不追求复杂 DTO 层级，只需要稳定、明确的查询结果对象，避免 Web 和飞书分别拼接岗位数据。

## 5. 飞书集成边界

建议新增：

```text
src/jobpicky/integrations/feishu/
├── connection.py
├── workspace.py
├── pull_state.py
├── push_jobs.py
└── notification.py
```

各模块职责：

- `connection.py`：凭据解析和连接测试；
- `workspace.py`：工作台创建、修复和验证；
- `pull_state.py`：用户状态回拉和保护；
- `push_jobs.py`：从核心查询结果构造并推送岗位；
- `notification.py`：每日通知。

首次连接飞书只做：

```text
测试连接 → 创建或修复工作台 → 读取本地推荐 → 首次同步
```

它不负责本地 seed 初始化、岗位抓取或匹配算法。

每日飞书流程为：

```text
DailyUpdateService 完成本地更新
    ↓
可选：回拉用户状态
    ↓
可选：推送推荐结果
    ↓
可选：发送通知
```

飞书集成失败只记录集成失败，不回滚已经提交的本地岗位、匹配和推荐结果。

## 6. 四阶段实施计划

### 阶段 1：建立可重复的 seed 数据源

目标：在不引入新业务服务的情况下，把现有 747 条岗位导出为权威 JSON，并从 JSON 生成新的 seed。数据库 schema 原则上保持当前业务含义，只修正明确阻碍新架构的问题，不进行无必要的字段重设计。

文件：

- 新增 `src/jobpicky/resources/jobs_seed_source.json`；
- 新增 `scripts/export_seed_source.py`；
- 新增 `scripts/build_seed.py`；
- 审查并按需轻度调整数据库 schema 定义文件；
- 重新生成 `src/jobpicky/resources/jobs_seed.sqlite`；
- 删除开发环境旧 `jobs.sqlite`。

任务：

- [ ] 从旧 seed 导出 747 条岗位到 JSON；
- [ ] 检查关键字段、空值和日期字段没有丢失；
- [ ] 对当前表结构做业务含义审查；
- [ ] 只调整明确阻碍核心服务的表或字段；
- [ ] 从 JSON 生成新 seed；
- [ ] 验证新 seed 可复制成运行数据库；
- [ ] 验证重复生成结果稳定。

测试：

- [ ] 新数据库能创建；
- [ ] 岗位总数为 747；
- [ ] 关键岗位字段逐项抽样或快照比对；
- [ ] seed 复制后可查询；
- [ ] 无飞书配置也能完成初始化。

验收：新 seed 可以独立支撑本地初始化，不读取旧运行数据库；schema 没有因为 seed 重建而发生无必要的重设计。

完成后删除：旧开发运行数据库。旧 seed SQLite 在 JSON 和新 seed 对比验收后可以删除；旧 SQLite 迁移代码不移植，确认无新调用者后删除。

风险和回滚：JSON 导出遗漏字段是最大风险。保留旧 seed 文件到阶段验收结束，确认 JSON 和新 seed 对比通过后再删除旧文件。

### 阶段 2：重构公共核心

目标：完成六个核心服务，并让初始化、每日更新、重新匹配、推荐查询全部不依赖飞书。

文件：

- 新增 `src/jobpicky/core/bootstrap.py`；
- 新增 `src/jobpicky/core/ingestion.py`；
- 新增 `src/jobpicky/core/matching.py`；
- 新增 `src/jobpicky/core/recommendations.py`；
- 新增 `src/jobpicky/core/daily_update.py`；
- 新增 `src/jobpicky/core/queries.py`；
- 重写或删除旧 `pipeline.py` 中重复流程；
- 暂时保留 `storage.py` 作为单一持久化实现，不在此阶段拆成多个持久化文件；只删除新架构不再需要的旧迁移和流程代码。

任务：

- [ ] 初始化、每日更新和重匹配统一使用核心服务；
- [ ] 统一岗位写入、去重和详情字段保护；
- [ ] 将匹配结果保存与推荐维护分离；
- [ ] 明确每日追加和全量重建；
- [ ] 将 `_job_from_row()` 等数据库映射移入查询或持久化层；
- [ ] 核心模块不导入 `feishu.py`、`audit.py`、Web 或 CLI。

测试：

- [ ] 新岗位去重写入；
- [ ] 变化岗位重新匹配；
- [ ] 详情未准备好的岗位不被错误匹配；
- [ ] 每日流程只处理新增或变化岗位；
- [ ] 全量重匹配可以重建推荐；
- [ ] 本地初始化、每日更新和查询不需要飞书配置。

旧代码处理：不保留复杂的新旧双轨，也不保留旧内部 wrapper。旧函数由新核心直接替换，测试同步改为测试新服务和真实用户入口。

验收：以下流程都能在无飞书配置下运行：

```text
初始化
每日更新
重新匹配
查询推荐岗位
```

风险和回滚：匹配算法本身不改，只移动调用位置。若结果变化，优先检查输入岗位、变化判断和推荐日期，不通过兼容开关掩盖问题。

### 阶段 3：接入本地 Web 和 CLI

目标：Web 和 CLI 都只调用公共应用服务，不直接执行核心业务步骤。

文件：

- 修改 `src/jobpicky/web/app.py`；
- 修改 `src/jobpicky/cli.py`；
- 修改 `src/jobpicky/services/web_state.py`；
- 删除 `TaskManager._run_local()` 中的 seed、匹配和扫描编排；
- 将 CLI 的 init/daily/rematch/export 改为调用公共应用服务。

目标调用方向：

```text
Web / CLI → 公共应用服务 → core/* → 本地数据库
```

入口层不得直接调用：

- `restore_seed_database`；
- `JobRepository`；
- `Matcher`；
- `WonderCVCrawler`；
- 飞书客户端。

`TaskManager` 只负责：

- [ ] 启动后台任务；
- [ ] 保存任务状态；
- [ ] 返回任务结果；
- [ ] 处理任务级异常。

测试：

- [ ] Web 和 CLI 调用同一公共应用服务；
- [ ] 本地 Web 不配置飞书也能初始化和每日更新；
- [ ] CLI 的 init/daily/rematch 结果正确；
- [ ] Web API 响应和页面所需字段正确；
- [ ] 完整 pytest 通过。

验收：Web 和 CLI 不再分别实现岗位抓取、匹配或推荐流程。

完成后删除：Web/CLI 中重复业务代码、旧 `TaskManager._run_local()` 主体、直接数据库访问。

风险和回滚：主要风险是异步任务结果和 CLI 输出变化。使用真实入口测试，不依赖旧内部 monkeypatch 路径。

### 阶段 4：重新接入飞书

目标：飞书成为可选输出和状态集成，不进入核心业务流程。

文件：

- 新增 `src/jobpicky/integrations/feishu/connection.py`；
- 新增 `src/jobpicky/integrations/feishu/workspace.py`；
- 新增 `src/jobpicky/integrations/feishu/pull_state.py`；
- 新增 `src/jobpicky/integrations/feishu/push_jobs.py`；
- 新增 `src/jobpicky/integrations/feishu/notification.py`；
- 简化 `src/jobpicky/services/initialization.py`；
- 简化 `src/jobpicky/services/synchronization.py`；
- 修改 Web 飞书连接路由和 CLI init。

任务：

- [ ] 首次连接只测试连接、创建工作台和首次推送；
- [ ] 首次连接从本地数据库读取推荐，不重新实现匹配；
- [ ] 每日核心更新先完成本地写入；
- [ ] 飞书状态回拉、推荐推送和通知作为可选步骤；
- [ ] 推送失败不回滚本地结果；
- [ ] 保持用户状态、备注和未知状态保护；
- [ ] 保持错误脱敏。

测试：

- [ ] 飞书未配置时核心流程通过；
- [ ] 飞书连接失败不破坏本地初始化；
- [ ] 工作台创建失败不会伪造同步成功；
- [ ] 推送失败后本地岗位和推荐仍存在；
- [ ] 用户状态回拉异常时不覆盖本地用户数据；
- [ ] 通知失败不影响本地和推送结果；
- [ ] 完整 pytest、wheel 和 `uvx` 启动测试通过。

验收：飞书可以拔掉，核心仍可独立运行；飞书接上后只消费核心结果和查询服务。

完成后删除：核心模块中的 `skip_feishu` 分支、pipeline 对 `audit.py` 的直接依赖、Web/CLI 内部飞书业务编排。

风险和回滚：重点验证同步字段、远端记录 ID、用户状态保护和部分批量失败。飞书集成失败只能标记集成失败，不能回滚本地事务。

## 7. 不做的事情

- 不维护旧运行数据库迁移；
- 不迁移旧用户状态；
- 不迁移旧飞书同步状态；
- 不保留旧内部函数和 monkeypatch 路径；
- 不拆成多个岗位 SQLite 文件；
- 不一开始拆成大量持久化小文件；
- 不一开始设计复杂 DTO 框架；
- 不顺手修改匹配算法；
- 不顺手修改推荐业务语义；
- 不做 UI 美化；
- 不引入新的 Web 框架。

## 8. 总体验收标准

- [ ] 单一运行数据库可以由 JSON/seed 重建；
- [ ] 747 条 seed 岗位完整保留；
- [ ] 本地初始化、每日更新、重新匹配和查询不依赖飞书；
- [ ] Web 和 CLI 调用相同公共应用服务；
- [ ] 飞书是可选集成；
- [ ] 飞书失败不破坏本地结果；
- [ ] 匹配和推荐语义未改变；
- [ ] 用户状态保护和错误脱敏未改变；
- [ ] 完整 pytest 通过；
- [ ] wheel 和 `uvx` 启动通过。
