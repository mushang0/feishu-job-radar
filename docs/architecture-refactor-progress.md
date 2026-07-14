# JobPicky 架构解耦重构进度

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

状态：未开始

### 开始前

- [ ] 阅读核心查询服务和本地应用服务。
- [ ] 只阅读飞书客户端、工作台、审计、字段映射和相关测试。
- [ ] 确认本地流程已经独立通过。

### 实际修改文件

```text
待填写
```

### 关键设计决定

```text
待填写
```

### 测试结果

```text
待填写
```

### 验收

- [ ] 首次连接只测试连接、创建工作台和首次同步。
- [ ] 首次连接不重新实现本地初始化和匹配。
- [ ] 每日核心更新先提交本地结果。
- [ ] 飞书状态回拉、推送和通知均为可选步骤。
- [ ] 飞书失败不破坏本地岗位、匹配和推荐。
- [ ] 用户状态保护和错误脱敏保持有效。
- [ ] 完整 pytest、wheel 和 `uvx` 启动通过。

### 遗留问题

```text
待填写
```

### 阶段提交

```text
commit: 待填写
```

### 重构完成检查

- [ ] `docs/architecture-refactor-plan.md` 中的总体验收标准全部完成。
- [ ] 所有开发环境旧运行数据库已删除并由新 seed 重建。
- [ ] 没有遗留的核心 → 飞书直接依赖。
- [ ] 没有遗留的 Web/CLI 重复业务流程。
- [ ] 匹配和推荐语义与阶段 1 基线一致。
- [ ] `python -m pytest -q` 通过。
- [ ] wheel 安装和 `uvx` 启动通过。

## 阶段变更记录

| 日期 | 阶段 | 变更摘要 | 测试结果 | Commit |
| --- | --- | --- | --- | --- |
| 2026-07-14 | 计划建立 | 创建并修订架构计划和进度文档，尚未修改源码 | 235 passed（初始基线） | 待提交；基线 `e832983` |
