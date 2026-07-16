# JobPicky 当前架构

本文是当前架构的主要入口，描述仓库现状。重构计划和进度仅作为历史实施资料。

## 分层与依赖方向

```text
Web (`web/app.py`) / CLI (`cli.py`)
    → 应用服务 (`services/`)
        → 核心服务 (`core/`)
            → `storage.py` / SQLite

飞书入口
    → `integrations/feishu/FeishuIntegrationService`
        → 查询/同步服务
        → `feishu.py`、`workspace_provisioner.py` 等底层客户端
```

`core` 是与传输方式无关的本地业务层，不知道 FastAPI、CLI 或飞书。`services` 组合用例、运行锁、报告和可选集成；入口层只负责参数校验、任务状态和输出。

## 主要目录

```text
src/jobpicky/
├── core/                         # 本地数据库、写入、匹配、推荐、查询
├── services/                     # 本地、每日、初始化、同步等应用用例
├── integrations/feishu/service.py # 飞书统一应用边界
├── web/app.py                    # FastAPI 路由与后台任务
├── cli.py                        # CLI 命令分派及维护命令适配
├── storage.py                    # SQLite repository 与 schema
├── pipeline.py                   # 仍在使用的维护/补全与回拉函数
├── feishu.py                     # 飞书 HTTP 客户端
├── wondercv.py                   # 岗位抓取与解析
└── resources/                    # 802 条岗位 seed 及 Web 模板
```

## 核心服务职责

- `DatabaseBootstrapService`：检查并从打包 seed 原子恢复本地库；不抓取、不匹配、不连接飞书。
- `JobIngestionService`：标准化、生成去重键并写入岗位；不决定匹配或推荐。
- `MatchingService`：调用 `Matcher` 并保存匹配结果；不抓取、不推送。
- `RecommendationService`：区分每日追加 `append_daily()` 与全量重建 `rebuild_all()`；不计算匹配规则。
- `DailyUpdateService`：编排抓取 → 写入 → 仅匹配变化岗位 → 每日推荐追加；不导入或调用飞书。
- `JobQueryService`：查询岗位、推荐和统计；不修改业务数据。

## 主要调用链

首次本地初始化：

```text
POST /api/local/start
→ TaskManager.start()
→ LocalApplicationService.initialize_and_update()
→ DatabaseBootstrapService.initialize()
→ MatchingService.rematch_all()
→ RecommendationService.rebuild_all()
→ run_daily_workflow()
→ DailyUpdateService.run()
```

每日更新（Web `POST /api/tasks/daily` 或 CLI `jobpicky daily`）：

```text
run_daily_workflow()
→ DailyRunGuard
→ WonderCVCrawler
→ DailyUpdateService.run()
→ enrich_official_urls()
→ FeishuIntegrationService.run_after_local_update()（配置时可选）
→ scan_runs / RunReport / vacuum
```

首次连接飞书（Web `/api/feishu/test`、`/api/setup/initialize` 或 CLI `init`）：

```text
existing_local_repository()（必须已有有效本地库）
→ FeishuIntegrationService.test_connection()
→ InitializationService.initialize()
→ FeishuIntegrationService.connect()
→ WorkspaceProvisioner.provision()
→ JobRepository.list_feishu_reconciliation_rows()
→ sync_feishu()
```

连接流程不会 seed、抓取、匹配或重建推荐。Web、CLI 的 daily 共享 `run_daily_workflow()`；本地初始化和 rematch 共享 `LocalApplicationService`/`rematch_local()`；飞书连接和日常同步共享 `FeishuIntegrationService`。

## SQLite 业务表

- `jobs`：规范化岗位主数据、来源、正文、解析状态和官网链接。
- `job_matches`：每个岗位的匹配结论、分数、理由和推送判断。
- `recommended_jobs`：按日期保存推荐集合及理由。
- `job_user_state`：用户求职状态和备注等用户拥有字段。
- `scan_runs`：初始化、扫描、重匹配等运行摘要与错误。
- `feishu_sync`：本地岗位与飞书 record ID、同步状态和错误的映射。

## 修改导航

- 匹配规则：`matcher.py`、`core/matching.py`、`tests/test_matcher.py`、`tests/test_core_services.py`。
- 岗位抓取：`wondercv.py`、`core/daily_update.py`、抓取和分页测试。
- 本地 WebUI：`web/app.py`、`web/templates/index.html`、`services/web_state.py`、Web 测试。
- 飞书同步：`integrations/feishu/service.py`、`services/synchronization.py`、`feishu.py`、`feishu_records.py`、workspace 与同步测试。
- 数据库字段：`storage.py`、`models.py`、seed 构建脚本及 storage/seed/schema 测试；同时检查所有查询和飞书字段映射。

## 新功能放置原则

稳定的本地业务规则放入 `core`；跨核心步骤的用户用例放入 `services`；外部平台编排放入 `integrations`；HTTP/CLI 参数和展示留在入口；SQL 与持久化细节留在 `storage.py`。新功能应向下依赖，不把入口或飞书配置传入核心服务。

## 保留的兼容和维护入口

- `pipeline.py` 保留 `backfill_existing_job_details()`、`enrich_official_urls()`、`run_init_with_page_batches()` 和 `pull_user_states_from_feishu()`：它们仍被 CLI 维护命令、每日集成或飞书服务调用，并有回归测试。
- CLI 的 `reset`、`backfill-details`、`enrich-official`、`pull`、`check` 等命令仍直接组合部分底层组件：这些是真实维护入口，不属于本阶段重构范围。
- `services/scanning.py::run_daily_with_jobs()` 是 `DailyUpdateService` 的薄适配层，保留其稳定测试 seam 和每日结果 DTO 转换职责，不包含独立业务循环。
- `services/synchronization.py::sync_feishu()` 保留为飞书底层批量同步实现，由统一集成服务和维护命令复用。

## 明确禁止的反向依赖

- `core` 禁止导入 `web`、`cli`、`integrations` 或任何飞书模块。
- Web 路由禁止直接操作 repository、`Matcher`、crawler、seed 或推荐循环。
- CLI 主流程禁止复制抓取、写入、匹配和推荐编排。
- 飞书连接禁止触发本地 seed、抓取、全量匹配或推荐重建。
- 本地核心禁止通过配置开关、兼容别名或回调变形依赖飞书实现。

以上边界由 `tests/test_architecture_boundaries.py` 的简单 AST 测试约束。
