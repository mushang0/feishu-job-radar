# JobPicky 架构解耦重构进度（历史实施资料）

> 本文记录历史实施过程。当前架构的主要入口是 [`architecture.md`](architecture.md)。

## 阶段 6：架构收尾、冗余清理和文档固化（2026-07-14）

删除：`pipeline.py::run_daily_with_jobs()` 与 `pipeline.py::rematch_existing_jobs()` 两套旧业务编排，以及仅转发到 `rematch_local()` 的 `cli.rematch_existing_jobs()` wrapper；生产代码无调用，测试改为验证当前公共服务。

保留：`pipeline.py` 的详情回填、官网补全、分页初始化和飞书用户状态回拉仍由维护命令、每日流程或飞书集成调用；CLI 维护命令、`scanning.run_daily_with_jobs()` DTO 适配层和 `sync_feishu()` 批量同步实现均有真实入口或明确边界职责。

结论：Web/CLI 主流程不存在第二套岗位写入、匹配或推荐循环；维护命令仍有专用编排，但不与首次初始化或每日核心流程重复。新增轻量 AST 架构测试，固化 core、Web、CLI 与飞书连接边界。完整验证结果和提交号见本阶段最终提交。

状态：阶段 2 已完成，等待合并到集成分支

计划文档：`docs/architecture-refactor-plan.md`

## 使用规则

- 每个阶段从最新的总集成分支创建独立分支。
- 阶段内允许按逻辑拆成 2～5 个小提交，不要求压成一个巨大 commit。
- 阶段验收通过后，使用 `--no-ff` 合并回总集成分支。
- 每个阶段开始前先阅读计划文档、本阶段相关源码和测试。
- 不重新扫描与本阶段无关的整个仓库。
- 阶段完成后记录实际修改、测试结果和遗留问题。
- 不在重构阶段顺手修改匹配算法、推荐语义或 UI。
- 阶段 1 的生产代码只在 seed/bootstrap 需要时修改；不在此阶段抽取核心业务服务。

## Git 分支与回退规则

分支结构：

```text
main
└── refactor/architecture
    ├── refactor/01-seed-bootstrap
    ├── refactor/02-core-services
    ├── refactor/03-web-cli
    └── refactor/04-feishu-integration
```

规则：

- [ ] 不直接在 `main` 或 `refactor/architecture` 上开发。
- [ ] 开始工作前记录 `git status --short`、当前分支和当前 commit。
- [ ] 每个阶段分支从最新的 `refactor/architecture` 创建。
- [ ] 阶段内可以按功能拆分多个小 commit，例如 seed 源、seed 测试和文档记录分别提交。
- [ ] 未通过完整测试、wheel 和 `uvx` 检查时禁止合并阶段分支。
- [ ] 阶段验收通过后使用 `git merge --no-ff` 合并回 `refactor/architecture`。
- [ ] 不覆盖用户已有未提交修改。
- [ ] 不使用 `git reset --hard`、`git clean -fd` 或强制推送，除非用户明确批准。
- [ ] 优先用 `git revert` 或回退到上一个阶段合并 commit 处理代码回退。
- [ ] 运行数据库回退使用 seed 重新生成，不依赖旧运行数据库迁移。

推荐的初始化命令：

```bash
git switch main
git pull
git switch -c refactor/architecture
```

阶段分支示例：

```bash
git switch refactor/architecture
git switch -c refactor/01-seed-bootstrap
```

阶段完成后：

```bash
git status --short
git diff --check
python -m pytest -q

git switch refactor/architecture
git merge --no-ff refactor/01-seed-bootstrap
```

## 初始状态

| 项目 | 状态 |
| --- | --- |
| 当前 Git commit | `e832983` |
| 当前分支 | `main` |
| 初始测试结果 | `235 passed in 23.64s` |
| 当前阶段 | 未开始 |
| 当前运行数据库 | 开发环境旧数据库，阶段 1 后删除重建 |
| seed 源数据 | 现有 `jobs_seed.sqlite`，747 条岗位 |
| 下一步 | 阶段 1：导出岗位源 JSON，审查当前 schema，生成新 seed |

## 阶段 1：建立可重复的 seed 数据源

状态：已完成（2026-07-14）

### 开始前

- [x] 阅读 `DEVELOPER.md`、seed 相关代码和数据库相关测试。
- [x] 确认旧 seed 的 747 条岗位和关键字段清单。
- [x] 审查当前 schema 的业务含义和新核心服务所需字段。
- [x] 明确只修正实际阻碍新架构的表或字段。
- [x] 确认不会读取或迁移旧运行数据库。

### 实际修改文件

```text
pyproject.toml
scripts/build_seed.py
scripts/export_seed_source.py
src/jobpicky/resources/jobs_seed_source.json
src/jobpicky/resources/jobs_seed.sqlite
tests/test_seed.py
docs/architecture-refactor-plan.md
docs/architecture-refactor-progress.md
```

### 关键设计决定

```text
1. JSON 是岗位 seed 的权威源，保存 jobs 表全部 41 列、显式 null 和原始 id，按 id 稳定排序；不加入会随构建变化的导出时间。
2. SQLite 由当前 JobRepository schema 创建，再从 JSON 显式按列插入；SQLite 只是可分发、可复制的构建产物。
3. 旧 seed 的历史追加列顺序与当前 schema 顺序不同。JSON 规范化为当前 schema 顺序，验收按列名比较；旧/新 seed 的 747×41 个值完全一致。
4. 现有六类业务表已满足阶段 1/后续服务的含义，本阶段未重设计 schema，也未读取或迁移任何旧运行数据库。
5. JSON 加入 wheel 包资源；运行时仍只复制打包 seed，阶段 2 核心服务未实施。
6. 开始时本地及远端均无 refactor/architecture；按计划记录的 main@e832983 基线建立本地集成分支，再创建 refactor/01-seed-bootstrap。
```

### 测试结果

```text
局部：26 passed（seed、初始化及 onboarding 相关测试）
完整：238 passed in 24.64s
数据：旧/新 seed 747 行 × 41 列逐值一致；完整保留空值与日期/时间字符串
重复构建：两次 SQLite 产物字节一致
发布检查：9/9 PASS（含 wheel 内容、干净安装、WebUI、uvx）
git diff --check：通过
```

### 验收

- [x] `jobs_seed_source.json` 已生成并作为岗位 seed 源文件。
- [x] `jobs_seed.sqlite` 可由 JSON 重新生成。
- [x] 新数据库包含 747 条岗位。
- [x] 关键字段没有丢失。
- [x] seed 可以复制为运行数据库。
- [x] 没有因为重建 seed 而进行无必要的 schema 重设计。

### 遗留问题

```text
无阶段 1 阻塞问题。旧 seed 的历史列顺序未保留，但字段集合、类型和值均保留；新 seed 使用当前 schema 的规范顺序。
阶段 2 仍需按计划实现公共核心服务；本阶段没有提前实施。
```

### 阶段提交

```text
当前分支：refactor/01-seed-bootstrap
实现 commit：2152963
进度文档 commit：本节所在的后续文档提交
```

### 下一阶段入口

阶段 2：实现 `src/jobpicky/core/` 下的公共核心服务。

## 阶段 2：重构公共核心

状态：已完成（2026-07-14）

### 开始前

- [x] 只阅读核心服务、`pipeline.py`、`storage.py`、`matcher.py`、`wondercv.py` 和本阶段测试。
- [x] 确认阶段 1 的新 seed 已通过验收。
- [x] 确认本地流程可以在无飞书配置下运行。

### 实际修改文件

```text
src/jobpicky/core/__init__.py
src/jobpicky/core/bootstrap.py
src/jobpicky/core/ingestion.py
src/jobpicky/core/matching.py
src/jobpicky/core/recommendations.py
src/jobpicky/core/daily_update.py
src/jobpicky/core/queries.py
src/jobpicky/pipeline.py
src/jobpicky/storage.py
tests/test_core_services.py
docs/architecture-refactor-progress.md
```

### 关键设计决定

```text
1. `JobRepository.upsert_job()` 继续作为去重、变化判断和详情字段保护的唯一持久化实现；写入服务只补齐公司标准化与 dedupe key。
2. `MatchingService` 原样复用 `Matcher`，只负责指定岗位或全量岗位匹配及结果保存；非 `detail_ready` 岗位不匹配。
3. `RecommendationService.append_daily()` 只追加当日推荐；`rebuild_all()` 根据全量重匹配结果重建全局推荐集合。
4. `DailyUpdateService` 只编排抓取、写入、匹配、推荐追加，并仅把新增或变化岗位交给匹配服务。
5. 数据库行到 `Job` 的映射移入 `JobRepository`；旧 pipeline 的增量写入、重匹配和分页初始化改为复用核心服务。
6. 核心服务不负责运行锁、扫描记录、Web 任务、CLI 输出、飞书回拉/推送、通知、审计或页面序列化。
7. 实际代码的 seed 恢复函数保留“目标存在则不覆盖”语义，`DatabaseBootstrapService` 在恢复后统一执行 schema 初始化。
```

### 测试结果

```text
局部：28 passed in 11.33s（核心、pipeline、推荐、初始化、storage、seed）
完整：244 passed in 24.66s
git diff --check：通过
发布检查：未运行；本阶段未修改打包资源、安装路径、入口或 wheel 内容
```

### 验收

- [x] `DatabaseBootstrapService` 可创建运行数据库。
- [x] `JobIngestionService` 可完成标准化、去重和写入。
- [x] `MatchingService` 可保存匹配结果。
- [x] `RecommendationService` 区分每日追加和全量重建。
- [x] `DailyUpdateService` 不导入飞书。
- [x] `JobQueryService` 可查询岗位、推荐和统计。
- [x] 初始化、每日更新、重新匹配和查询均不需要飞书。

### 遗留问题

```text
阶段 2 无阻塞问题。旧 `pipeline.py` 中飞书回拉、详情回填和官网 URL 补全入口仍保留，供阶段 3/4 按入口与集成边界继续迁移；WebUI、CLI 和飞书流程本阶段未接入新服务。
```

### 阶段提交

```text
当前分支：`refactor/02-core-services`
实现 commit：`328d32d`
进度文档 commit：本节所在的后续文档提交
```

### 下一阶段入口

阶段 3：让 Web 和 CLI 只调用本阶段公共核心服务；不在入口层重复编排数据库、Matcher 或 crawler。

## 阶段 3：接入本地 Web 和 CLI

状态：已完成（2026-07-14）

### 开始前

- [x] 阅读新的 `src/jobpicky/core/` 服务。
- [x] 只阅读 Web、CLI、TaskManager 和相关入口测试。
- [x] 确认核心服务已经可以脱离飞书运行。

### 实际修改文件

```text
src/jobpicky/cli.py
src/jobpicky/services/local.py
src/jobpicky/services/scanning.py
src/jobpicky/services/web_state.py
src/jobpicky/web/app.py
tests/test_daily_workflow.py
tests/test_initialization_cli.py
tests/test_mvp_onboarding.py
docs/architecture-refactor-progress.md
```

### 关键设计决定

```text
1. 新增轻量 `LocalApplicationService`，只组合 `DatabaseBootstrapService`、`MatchingService`、`RecommendationService` 和既有 daily 集成入口；不实现任何写库、匹配或推荐循环。
2. Web 本地初始化调用链为：路由 -> `LocalApplicationService` -> bootstrap/全量匹配/推荐重建 -> `run_daily_workflow(skip_feishu=True)` -> `DailyUpdateService`。
3. Web/CLI daily 调用同一 `run_daily_workflow`；其中本地处理阶段统一委托 `DailyUpdateService`，飞书回拉、官网补全、同步和通知边界暂时保留原实现。
4. CLI init/rematch 通过 bootstrap、query 和本地 rematch 应用服务完成本地工作；保留飞书预检、工作台、同步、输出、退出码及扫描记录边界。
5. Web 岗位与健康统计通过 `JobQueryService` 查询；CLI 推荐导出也通过该查询服务。
6. `TaskManager` 接收路由注入的操作，只负责任务启动、互斥、状态、取消、异常兜底和结果保存；新增 `DELETE /api/tasks/{task_id}` 取消入口。
7. 删除 Web `_run_local()` 中的 seed 恢复、仓储初始化、全量重匹配和 daily 编排；替换 scanning 对旧 pipeline 本地处理函数的依赖。
8. 实际代码与计划的差异：旧 daily 集成仍承载运行锁、扫描记录和阶段 4 的飞书边界，因此本阶段仅把其本地处理段切入核心服务，没有提前拆除飞书逻辑。
```

### 测试结果

```text
局部：51 passed（Web、CLI、daily、初始化和核心服务）
完整：245 passed in 28.34s
git diff --check：通过
发布检查：9/9 PASS（含 wheel、干净安装、仓库外 WebUI、uvx 和干净退出）
```

### 验收

- [x] Web 路由不直接调用 seed、数据库、Matcher 或 crawler。
- [x] CLI 的 init/daily/rematch 使用公共应用服务。
- [x] TaskManager 只负责后台任务和状态。
- [x] 本地 Web 和 CLI 结果正确。
- [x] 不配置飞书也能完成本地工作流。

### 遗留问题

```text
阶段 3 无阻塞问题。`services/scanning.py` 仍保留飞书回拉、官网 URL 补全、同步和通知；CLI init/rematch 仍保留飞书工作台与同步边界，按计划留给阶段 4。旧 pipeline 的详情回填等维护命令未在本阶段迁移。
```

### 阶段提交

```text
当前分支：`refactor/03-web-cli`
起点 commit：`8aec8c7`
实现与验收 commit：`e29086d`
进度文档 commit：本节所在的后续文档提交
```

### 下一阶段入口

阶段 4：重新接入飞书集成。

### 阶段 3 独立审查修复（2026-07-14）

```text
修复 TaskManager 取消终态：收到取消请求后，即使 daily/local 返回失败结果，最终状态仍稳定为 cancelled；未收到取消请求的普通失败保持 failed。
将 cancelling 纳入活动任务状态，上一任务真正结束前继续拒绝新的 local/daily 任务。
取消测试改为通过 DELETE API 发起，验证 cancelling 期间的 409 互斥和最终 cancelled；各等待阶段使用独立超时并在超时时明确失败。
新增 LocalApplicationService.initialize_and_update() 结果型集成测试，验证真实 seed/bootstrap、全量匹配、推荐重建、单次 daily 更新、数据库结果和无飞书配置运行。
完整测试：247 passed in 39.24s
发布检查：9/9 PASS
git diff --check：通过
提交：本修复提交（fix: preserve cancellation state and task exclusivity）
```

## 阶段 4：重新接入飞书

状态：已完成（2026-07-14）

### 开始前

- [x] 阅读核心查询服务和本地应用服务。
- [x] 阅读飞书客户端、工作台、审计、字段映射和相关测试。
- [x] 确认本地流程已经独立通过。

### 实际修改文件

```text
src/jobpicky/integrations/__init__.py
src/jobpicky/integrations/feishu/__init__.py
src/jobpicky/integrations/feishu/service.py
src/jobpicky/services/initialization.py
src/jobpicky/services/local.py
src/jobpicky/services/scanning.py
src/jobpicky/cli.py
tests/test_daily_workflow.py
tests/test_initialization_cli.py
tests/test_mvp_onboarding.py
docs/architecture-refactor-progress.md
```

### 关键设计决定

```text
1. 新增 FeishuIntegrationService，统一凭据连接测试、WorkspaceProvisioner 工作台创建/修复、用户状态回拉、岗位/推荐推送和机器人通知；继续复用 FeishuBitableClient、FeishuBot、字段映射、审计保护和同步状态表。
2. 首次连接调用链固定为：连接测试 → 工作台创建/修复 → 查询本地同步候选/推荐 → 首次同步。InitializationService 和 CLI init 均不再恢复 seed、抓取 WonderCV、全量匹配或重建推荐。
3. 每日调用链调整为：抓取 → 本地岗位提交/匹配/推荐 → 官网链接补全 → 可选飞书回拉 → 可选推送 → 可选通知。飞书各阶段只在本地结果落库后运行，异常转换为集成阶段错误，不回滚本地结果。
4. 官网链接补全不再受飞书配置或 CLI --no-feishu 控制，补全策略仍为 only_recommended=True。
5. 公共每日服务删除 skip_feishu 参数；CLI --no-feishu 仅在入口复制配置并移除飞书段，本地初始化服务采用相同入口选择，不向公共服务传递飞书开关。
6. 回拉存在异常时继续阻止推送，避免覆盖用户字段；通知与推送相互隔离。同步继续维护 record_id、sync_status、部分批量失败和脱敏错误。
7. 实际代码与计划差异：计划建议拆成 connection/workspace/pull_state/push_jobs/notification 五个文件；实际职责较薄且共享事务边界，集中为 integrations/feishu/service.py，底层模块保持原位，避免无必要重写。
```

### 测试结果

```text
局部测试：37 passed（daily、本地应用、审计、字段映射、同步候选）。
完整测试：247 passed in 57.50s。
发布检查：9/9 PASS（build、wheel 校验、干净环境安装、依赖检查、仓库外启动、WebUI health、uvx smoke、干净退出全部通过）。
git diff --check：通过。
```

### 验收

- [x] 首次连接只测试连接、创建工作台和首次同步。
- [x] 首次连接不重新实现本地初始化和匹配。
- [x] 每日核心更新先提交本地结果。
- [x] 飞书状态回拉、推送和通知均为可选步骤。
- [x] 飞书失败不破坏本地岗位、匹配和推荐。
- [x] 用户状态保护和错误脱敏保持有效。
- [x] 完整 pytest、wheel 和 `uvx` 启动通过。

### 遗留问题

```text
旧 reset、rematch、audit、backfill 等维护命令仍直接使用底层飞书组件；它们不是本阶段的首次连接或每日核心调用链。services/scanning.py 仍保留兼容结果 DTO 和阶段报告，后续可在不改变 API 的前提下进一步瘦身。
```

### 阶段提交

```text
分支：refactor/04-feishu-integration
阶段起点：54cea4a
实现提交：8c44445
文档与最终验收提交：本提交
```

### 阶段 4 独立审查修复（2026-07-14）

```text
修复 CLI 首次连接边界：只读检查既有本地数据库，不再恢复 seed、调用 DatabaseBootstrapService、抓取 WonderCV、全量重匹配或重建推荐；缺少已初始化数据库时返回明确且脱敏的操作提示。
Web 飞书连接路由不再直接构造 FeishuBitableClient 或调用 get_app()，改为与 CLI 一致调用 FeishuIntegrationService.test_connection()。
首次连接统一为：检查本地数据库 → 测试连接 → 创建或修复工作台 → 查询本地推荐 → 首次同步；CLI 输出不再声称已重新匹配。
首次同步和每日同步统一使用 list_feishu_reconciliation_rows()：包含当前推荐、受跟踪状态和已有 record_id 的历史记录。退出推荐的已有远端记录保留不删除，通过系统字段“当前推荐=false”解除当前推荐标记，并继续禁止更新求职状态和备注。
工作台 schema 升级到版本 3，新增 checkbox 系统字段“当前推荐”。
新增/调整入口和同步测试，覆盖禁止本地初始化、缺库错误、Web/CLI 统一连接服务、退出推荐 reconciliation、用户状态与备注保护，并保留创建、更新、部分失败和错误脱敏回归覆盖。
针对性测试：47 passed；最终补充验证：17 passed。
完整测试：250 passed in 54.37s。
发布检查：9/9 PASS。
git diff --check：通过。
修复提交：42b0870（fix: unify Feishu onboarding and reconciliation）。
```

### 重构完成检查

- [x] `docs/architecture-refactor-plan.md` 中的总体验收标准全部完成。
- [x] 仓库运行数据策略已在阶段 1 改为由新 seed 重建（用户目录中的仓库外数据库不做破坏性清理）。
- [x] 没有遗留的公共核心 → 飞书直接依赖。
- [x] Web/CLI 的首次连接和每日流程复用同一飞书应用服务。
- [x] 匹配和推荐语义与阶段 1 基线一致。
- [x] `python -m pytest -q` 通过。
- [x] wheel 安装和 `uvx` 启动通过。

### 最终验收修复（2026-07-14）

最终验收发现 `InitializationService.preview()` 会对不存在的运行数据库调用
`init_schema()`，从而提前创建空 schema，并使后续 seed 恢复因目标文件存在而被跳过。
本次在 `refactor/05-final-fixes` 完成以下修复：

```text
1. setup preview 改为完全只读：只读检查有效运行数据库；缺库、空 schema 或无效库时，只读打包 seed 返回 747 条基线数量。连续 preview 不创建数据库、不迁移 schema，也不修改配置或 seed。
2. 新增统一只读数据库检查，明确区分 missing、empty_schema、invalid 和 valid；只有具备全部本地业务表且 jobs 中至少有一条岗位的数据库才是有效本地初始化结果，不依赖固定岗位 ID。
3. DatabaseBootstrapService 对缺库、空 schema 和无效库明确从打包 seed 原子重建；已有岗位数据的有效库继续保留。preview → 本地初始化和历史空 schema → 本地初始化均恢复为 747 条岗位。
4. Web 与 CLI 飞书连接前置检查复用同一有效性判定；缺库或空 schema 时在连接、工作台创建和首次同步之前停止，并返回脱敏且可操作的“请先完成本地初始化”提示。
5. CLI init 帮助与说明改为“连接飞书并同步已有本地推荐”，明确不会恢复 seed、抓取岗位或重新匹配。
6. 将 Web preview 的 `baseline_items >= 0` 弱断言改为精确的 747，并增加 preview 幂等无落盘、空 schema seed 恢复、有效库保留、Web/CLI 飞书保护及正常初始化后连接等真实数据库回归覆盖。
```

验收结果：

```text
针对性测试：25 passed
完整测试：254 passed in 70.69s
发布检查：9/9 PASS
git diff --check：通过
实现提交：4295807（fix: keep setup preview read-only）
```

## 阶段变更记录

| 日期 | 阶段 | 变更摘要 | 测试结果 | Commit |
| --- | --- | --- | --- | --- |
| 2026-07-14 | 计划建立 | 创建并修订架构计划和进度文档，尚未修改源码 | 235 passed（初始基线） | 待提交；基线 `e832983` |
