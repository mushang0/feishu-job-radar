# Feishu Job Radar：内部现状、问题与优化备忘

> 内部维护文档，不面向普通用户，不提交 Git。最后审计：2026-07-12；代码基线：`4f42b2a`。
>
> 本文记录的是可复核的现状、曾经踩过的问题和下一轮改进建议。README 才是普通用户文档。

## 1. 当前仓库与交付状态

### 1.1 发布边界

- 产品是 Windows 优先的本地、单用户 Python 工具；没有 SaaS、OAuth、账号体系或云端调度。
- 公开岗位来源当前只有 WonderCV；SQLite 是本地事实来源，飞书 Base 是用户的求职工作台。
- 首次运行入口是 `start.bat`：创建 Python 3.11 `.venv`、安装项目、进入 `init` 向导。日常入口为 `start.bat daily`。
- 对外只应保留 README、示例配置、源码、测试、seed 数据库和启动脚本。运行配置、真实数据库、日志、导出、备份、虚拟环境均不应提交。

### 1.2 本次审计后的“新用户初始状态”

已清理本地 `config.yaml`、`data/jobs.sqlite`、导出目录、`.venv` 和受管飞书“求职工作台”；仓库仅保留：

```text
data/jobs_seed.sqlite     # 随项目交付的只读岗位基线
data/backups/, data/logs/ # 忽略目录，可由运行时生成
config.example.yaml       # 不含凭据
```

不要把任何用户 Base、App Secret、运行库或真实岗位导出重新放回仓库。删除远端表仅限明确指定的受管“求职工作台”，不能删除 Base 里的其他用户表。

### 1.3 最近已完成的真实验收

在干净环境下用真实飞书 Base 验证过：自动创建虚拟环境与依赖、中文向导、seed 恢复、工作台创建、推荐和飞书同步。一次真实 `daily` 完成了三页详情抓取，随后因第四页岗位均已存在而停止；摘要为：抓取 36、新增 26、推荐 6、详情回填 36、飞书创建 6、更新 6、失败 0。`check` 与 `pull` 均零差异。

最近完整自动测试结果为 **169 passed**。本次仅做静态审计和清理，未重新创建环境运行测试。

## 2. 代码结构与数据流

```text
start.bat / run_daily.bat
        │
        ▼
cli.py ── onboarding.py / config.py / diagnostics.py
  │ init/reset                │
  ├── seed.py ── jobs_seed.sqlite ── storage.py (SQLite)
  ├── workspace_schema.py ── workspace_provisioner.py ── feishu.py
  │                                                     │
  └── daily ── run_guard.py ── wondercv.py ── pipeline.py ── matcher.py
                                                       │
                                            official_search.py / feishu_records.py
```

| 区域 | 主要模块 | 职责 |
| --- | --- | --- |
| 命令与体验 | `cli.py`, `onboarding.py`, `start.bat`, `run_daily.bat` | 命令路由、首次输入、运行摘要、启动环境。 |
| 配置与安全 | `config.py`, `diagnostics.py`, `logging_utils.py` | 默认配置、UTF-8 原子保存、预检查、日志。 |
| 采集与解析 | `wondercv.py`, `normalizer.py`, `models.py` | 列表/详情请求、HTML 解析、字段规范化、去重键。 |
| 匹配 | `matcher.py`, `pipeline.py` | 偏好展开、关键词/公司/城市规则、推荐落库。 |
| 本地存储 | `storage.py`, `backup.py`, `seed.py` | SQLite schema、增量写入、同步状态、seed 恢复与备份。 |
| 飞书工作台 | `feishu.py`, `workspace_schema.py`, `workspace_provisioner.py`, `feishu_records.py`, `audit.py` | 表/字段/视图创建，批量记录同步，状态回收与差异检查。 |
| 辅助输出 | `official_search.py`, `exporters.py`, `alerts.py` | 官方入口候选、Excel、机器人消息。 |

关键事实：`jobs` 保存抓取事实；`job_matches` 保存当时的匹配结论；`recommended_jobs` 保存推荐集合；`feishu_sync` 保存本地到远端的映射/重试状态；`job_user_state` 保存从飞书回拉的用户状态。不要让飞书内部字段反向成为本地事实来源。

## 3. 已遇到的问题与当前解决方式

### 3.1 中文与 Windows 编码

问题：PowerShell/CMD、管道输入和 UTF-8 批处理文件组合会导致中文提示、偏好或 YAML 变成乱码。

当前处理：

- `config.py` 用 UTF-8 + `allow_unicode=True` 原子写 YAML；读取显式 UTF-8。
- `start.bat` 使用 UTF-8 代码页和 `PYTHONUTF8=1`；批处理文件必须维持 **UTF-8 无 BOM、CRLF**，否则 CMD 可能把首行当成非法命令。
- `onboarding.py` 的 App Secret 在 TTY 上使用隐藏输入；自动化管道仅用于测试。
- 验收时以 YAML/SQLite 的 Unicode 值核对，不能只凭终端捕获器的显示判断。

仍需注意：从旧版 Windows CMD 或第三方任务计划器传入中文时，应该继续保留端到端编码测试；不要把 `config.yaml` 写成系统本地编码。

### 3.2 虚拟环境与一键部署

问题：直接执行系统 `python` 可能命中 Python 3.10，而项目声明最低 3.11；手工创建 venv 对普通用户不友好；半成品 venv 会导致后续启动表面成功、实际缺依赖。

当前处理：`start.bat` 通过 `py.exe -3.11` 创建 `.venv`；每次先验证 `import job_monitor`，导入失败即重新执行 `pip install -e .`。`run_daily.bat` 只使用项目内 `.venv`。

风险：首次网络安装仍依赖 PyPI 可达性。下一步可提供带哈希的锁文件、离线 wheel 缓存或更明确的代理/证书错误提示。

### 3.3 日常扫描的“超时”和进度

问题：此前 60 秒是外部验收器对父命令的时间上限，不是 WonderCV 详情请求失败。详情默认单请求 20 秒、且逐条等待，完整扫描自然可能持续数分钟；旧实现没有即时可见进度。

当前处理：列表页和每一条详情前后都 `flush=True` 输出进度；已处理整页在详情请求前停止；每条详情完成后才处理下一条。保留详情回填，不能为了快而关闭详情。

风险：默认最多 20 页 × 多条详情，最坏耗时仍高。应将“预计剩余量/已耗时/可恢复位置”显示给用户，而不是缩短正确的详情请求。

### 3.4 启动器被杀后仍有后台扫描

问题：在 Windows 上，仅杀掉外层 `cmd.exe` 可能留下虚拟环境 shim 和实际 Python 子进程，造成重复扫描/同步竞争。

当前处理：

- `DailyRunGuard` 用原子锁文件阻止第二个 `daily`；失效锁按 PID 恢复。
- `start.bat` 传入实际外层 CMD PID；`run_guard.py` 监控它。父启动器消失后，抓取器在当前网络请求边界停止，CLI 在本地写入和飞书同步前返回 `interrupted`。
- Windows PID 存活检查使用 `OpenProcess + GetExitCodeProcess(STILL_ACTIVE)`；**不能**用 `os.kill(pid, 0)`，它在 Windows 可能终止目标进程。

剩余边界：硬杀实际 Python 进程本身无法运行清理代码；锁文件会在下次启动时安全回收。批量飞书请求已经发出时不能回滚远端，应继续依靠幂等 record ID、重试和 `check`。

## 4. 当前核心风险与潜在 Bug

按优先级排序；以下是审计判断，不代表已实现。

### P0/P1：数据正确性与用户信任

1. **已有岗位详情更新后未重新匹配。** `run_daily_with_jobs` 只对 `created` 的岗位执行 `Matcher.match`/`save_match`；已有岗位即使详情、标题、城市或批次被 `upsert` 更新，也只是计为 `updated_items`。这会使匹配结论和推荐理由滞后，尤其恰好违背“详情回填提高准确性”的目标。应基于内容哈希/关键字段变化重新匹配，并在结论变化时安全更新推荐与飞书。
2. **列表/详情解析质量目前主要是启发式。** `_CardParser` 以 `<a>` 和 class 猜卡片，`_parse_card_text` 以 token 位置猜公司、标题和标签；详情页又以少量中文 marker 截取。网页一改版就可能把公司名当职位、把页面导航/提示词当正文（真实样本曾出现“请只返回 JSON”类噪声）。
3. **`ai`、`互联网`、`部署`等输入过宽。** 纯子串匹配会把公司简介、行业描述或无关营销文本当岗位方向命中；公司优先规则还可能放大不相关职位。当前排除词不足以保证 precision。
4. **官方入口不保证官方。** `OfficialUrlFinder` 依赖 Bing HTML 结构和手工评分/黑名单；没有对域名归属、职位页存在性、跳转链和有效期做验证，低置信度时会回退到搜索结果 URL，容易被用户误解为投递链接。
5. **批量同步的远端原子性不可保证。** 飞书已创建但本地进程在写回 record ID 前中断时，会出现远端记录存在、本地 `pending` 的可重试状态；重复命令通常能修复，但需要更精确的结果回读与幂等键策略。

### P1/P2：稳定性与可维护性

6. **单数据源单点故障。** WonderCV 页面、反爬、登录/验证码、HTML 结构变化都会使发现能力骤降；现在只有页面级错误，缺少来源健康度、样本快照和结构漂移告警。
7. **详情抓取无持久断点。** 日常扫描中断后下一次会从列表再走，依赖去重停止；没有按 job/page 保存抓取队列和详情完成状态，网络波动下会浪费请求。
8. **时间语义混杂。** `collected_date`、网页发布时间、首次发现、推荐日期、截止日期混用；“最新/旧岗位”与“本次新发现”可能不一致。需要明确 event time 与 ingest time。
9. **SQLite 每条写操作均开新连接。** 个人规模暂可接受，但大量详情/匹配/同步时性能和锁竞争会变差。应在单次运行中使用事务批量写入。
10. **配置版本/迁移策略较弱。** YAML 默认值深合并方便，但用户配置与 taxonomy 的演进没有显式 schema version 和兼容/弃用提示。
11. **中断检查的覆盖范围仍应扩大。** 当前取消信号在抓取阶段和抓取完成后的首个边界检查；若启动器恰好在本地匹配、官方入口补充或飞书批量请求期间消失，该阶段仍可能自然完成。后续应把取消令牌传到每个阶段和批次边界，并把“已发送、待对账”的飞书批次写入运行记录。
12. **seed 的新鲜度会影响首次体验。** 初始推荐完全依赖 `jobs_seed.sqlite`，如果 seed 长时间未更新，用户首次看到的是旧岗位或已截止岗位。应在 seed 中记录生成时间、来源覆盖范围和过期策略；首次界面要明确这是“离线基线”，日常扫描才是新增发现。

## 5. 推荐质量与提取质量：下一轮方案

### 5.1 先建立可测量的数据质量闭环

建立一个不含凭据的版本化标注集（建议 100–300 条）：原始列表 HTML、详情 HTML、期望公司/职位/届别/批次/城市/截止日/投递入口、相关性标签。每次改 parser 或 matcher 都输出：字段准确率、详情覆盖率、推荐 precision/recall、官方入口有效率。没有指标不要仅凭少数样本调整关键词。

### 5.2 分层解析，而不是一次性字符串猜测

1. 保存原始 HTML 哈希、解析器版本和结构化 JSON 中间结果；页面改版可比对与重放。
2. 列表页优先使用稳定 DOM 属性、JSON-LD、内嵌 JSON 或网络接口；`HTMLParser`/token 回退只是末级方案。
3. 详情页按明确区块（职位名称、公司、岗位职责、任职要求、工作地点、投递链接、发布时间）提取，分别保留字段来源和置信度；移除导航、页脚、推荐区与脚本。
4. 对职位名、公司名设置合理长度和垃圾文本校验；低置信度标为 `partial`，不要把猜测写成事实。
5. 详情更新按 `content_hash` 驱动重解析、重匹配和必要的飞书更新。

### 5.3 改进匹配：候选召回与精排分离

1. **召回层**：把用户输入映射到 canonical role group；只在职位名、职责、要求等角色字段中查找，不默认在公司简介全文查找。公司/城市/届别单独做过滤或加分。
2. **精排层**：为每个角色组维护 must-have、strong、weak、negative 和相邻岗位词；如“推理部署”应组合模型推理/框架/部署词，不应因单独 `ai` 命中。
3. 明确硬过滤：毕业届别、批次、城市、强排除职位优先于重点公司；重点公司只能提升优先级，不能绕过“销售/运营”等排除。
4. 输出可解释证据：命中的是职位名、职责还是公司规则；低置信度可不自动同步，只保存在本地待后续信息补足。
5. 引入用户行为反馈时只学习“收藏/不合适”的弱信号，并保留可撤销规则；不要直接上不可解释的黑箱模型。

### 5.4 改进投递入口：证据链与分级

优先级应为：详情页明确的投递 URL → 公司已验证招聘域名/ATS 域名 → 官方招聘页搜索结果 → 来源详情页。每个 URL 保存 `link_type`、发现方式、验证时间、HTTP 状态、最终域名与置信度。若只找到搜索结果，字段应写“待核验入口”或保留来源页，不能标作“官方投递入口”。

建立公司招聘域名注册表（可逐渐积累、可审核），并对候选 URL 做 HEAD/GET 重定向验证、域名 allowlist、职位/招聘语义检查。搜索结果的 HTML 解析应替换为可切换 provider，并缓存查询/结果以避免限流。

### 5.5 运行体验优化路线

1. 显示阶段、页码、详情进度、已耗时、预计剩余量和“可安全停止”的提示。
2. 把抓取队列、详情状态和页面游标持久化；恢复时只做未完成详情。
3. 网络重试采用指数退避和来源级熔断；将“没有新岗位”“来源不可用”“解析结构变化”区分展示。
4. 对飞书同步采用分批回读/请求 id 记录，失败后自动对账，而不是仅按批量 API 返回推断。
5. 保留 `check` 的只读安全性，并新增 `doctor`：Python 版本、依赖、编码、网络、飞书权限、锁状态、seed 完整性与最近运行诊断。

## 6. 后续维护顺序

1. 先修复“详情更新不重匹配”，并为其写回归测试。
2. 建立解析标注集和字段质量指标；在此基础上重构 WonderCV 详情区块提取。
3. 收紧角色匹配域和负向规则，使用标注集校准 precision/recall。
4. 为投递入口引入置信度/域名验证，避免把搜索页当官方链接。
5. 最后做断点续抓、批量事务、来源健康度和多来源扩展；不要在质量指标缺失前贸然扩展爬虫数量。

## 7. WebUI 统一重构计划（2026-07-13）

本节是下一轮可执行的重构基线。目标不是在旧入口上继续叠加页面，而是将产品统一为：

> 本地运行的 WebUI 求职工具，浏览器负责交互，Python 负责抓取、匹配、存储和飞书同步。

当前审计结果：源码、测试、启动脚本、PyInstaller spec 和桌面 GUI 均已检查；现有自动化测试为 175 项通过。`.venv/`、缓存、`build/`、`dist/` 和 `.worktrees/` 已被忽略但仍可能存在于本地，不应作为源码交付物。`DEVELOPER.md` 本身应纳入 Git，不再被 `.gitignore` 忽略。

### 7.1 目标边界

最终结构按职责划分为：

```text
src/job_monitor/
├── core/            # 模型、匹配、规范化、taxonomy
├── sources/         # WonderCV、官方链接来源
├── services/        # 初始化、扫描、推荐、同步、诊断
├── integrations/    # 飞书 client、记录、工作台、审计
├── storage/         # repository、schema、迁移、备份、seed
├── resources/       # seed、默认规则、模板
├── web/             # FastAPI、路由、模板、静态资源
├── paths.py         # LocalAppData 路径
├── settings.py      # 用户配置与运行设置
└── launcher.py      # 启动服务、端口检测、打开浏览器
```

用户数据统一放到 `%LOCALAPPDATA%\\FeishuJobRadar\\`，包括 `config.yaml`、`jobs.sqlite`、`logs/`、`exports/` 和 `backups/`。旧版根目录的配置和数据库只做一次性复制迁移，迁移前备份并执行 SQLite 完整性校验。

### 7.2 文件处置原则

- `models.py`、`matcher.py`、`normalizer.py` 保留并迁移到 `core/`。
- `wondercv.py`、`official_search.py` 拆分到 `sources/`，将 HTTP、解析和来源协议分开。
- `pipeline.py` 和 `cli.py` 中的业务编排拆到 `services/`；CLI 仅作为过渡适配器，最终不作为普通用户入口。
- `feishu.py`、`feishu_records.py`、`audit.py`、`workspace_schema.py`、`workspace_provisioner.py` 迁移到 `integrations/feishu/`。
- `storage.py` 拆成 repository、schema、migration；`backup.py` 和 `seed.py` 迁移到 `storage/`。
- `desktop.py`、`desktop_entry.py`、`packaging/`、PySide6/PyInstaller 依赖、三个批处理入口，在 WebUI launcher 完成验收后删除。
- `data/jobs_seed.sqlite` 移入包内 resources，并增加 wheel 安装后的资源 smoke test；不能依赖当前工作目录寻找 seed。
- README 只保留普通用户的 uv/uvx 安装和启动说明；开发、测试、迁移、发布说明放在本文件。

### 7.3 阶段与依赖

依赖顺序为：

```text
阶段 0 保护网
  ↓
阶段 1 AppPaths、资源与迁移基础
  ↓
阶段 2 服务层抽取（CLI 仅适配）
  ↓
阶段 3 WebUI 旁路入口与向导
  ↓
阶段 4 launcher 和 LocalAppData 正式切换
  ↓
阶段 5 删除桌面、EXE、PowerShell 和公共 CLI 遗留
  ↓
阶段 6 PyPI、CI、README 和发布验收
```

每个阶段单独提交；阶段之间保留可运行状态。数据库迁移只复制不移动，旧入口在新入口通过验收前不删除。

#### 阶段 0：冻结行为并补齐契约测试

目标：不改变生产行为，锁定抓取、匹配、SQLite、推荐和飞书同步的现有契约。

涉及：`tests/fixtures/`、pipeline/storage/Feishu 测试。

必须覆盖：详情或关键字段变化后的重匹配、推荐幂等、飞书批量回执不足、pull 异常阻断同步、schema 升级备份、固定 WonderCV HTML 解析快照。

验收：原有测试和新增契约测试全部通过；不改变用户路径和入口。失败时只回滚测试提交。

#### 阶段 1：路径、包资源和迁移基础

新增 `paths.py`、`settings.py`、`storage/migrations.py` 和包内 seed/default resources。通过 `AppPaths` 和 `FEISHU_JOB_RADAR_HOME` 注入路径；旧根目录文件复制到 LocalAppData，写迁移 marker，保留备份和校验结果。

验收：从 wheel 安装也能找到 seed、模板和静态资源；空目录可初始化；旧配置和数据库可无损复制；原项目文件不被修改。默认仍可由旧 CLI 使用，便于回滚。

#### 阶段 2：服务层抽取

将 init、daily、rematch、pull、check、export、官方链接补全和 Feishu sync 从 `cli.py` 拆成结构化 service。服务不得 `print()`、解析 argparse、打开浏览器或依赖 PySide6/FastAPI。

验收：CLI 与服务对固定 fixture 产生等价数据库和运行报告；测试不再依赖 CLI 私有实现；服务可被 Web 直接调用。

#### 阶段 3：WebUI 旁路入口

新增 `web/app.py`、路由、模板、静态资源和任务状态 API。首版包含三步向导、偏好标签、飞书连接检查、工作台预览、每日扫描、进度、健康检查和打开工作台。使用进程内任务管理、`DailyRunGuard` 和 SSE/轮询，不引入队列基础设施。

验收：Web 不直接访问 crawler、sqlite 或 Feishu HTTP client；页面刷新不会重复任务；凭据不出现在响应和日志；CLI 与 Web 对 fixture 结果一致。

#### 阶段 4：launcher 与正式数据路径切换

新增 launcher，选择 `127.0.0.1` 可用端口，启动服务、等待健康检查并打开浏览器。正式入口改为 `job_monitor.launcher:main`，默认使用 `%LOCALAPPDATA%\\FeishuJobRadar\\`。

验收：从任意目录执行 `uvx --python 3.12 feishu-job-radar` 可启动；端口冲突、重复启动、优雅退出和旧版一次性迁移均有测试。

#### 阶段 5：删除旧发行路径

删除桌面 GUI、desktop entry、PyInstaller spec、三个批处理入口、desktop optional dependency、desktop console script 和 CI 中的 PyInstaller。CLI 中仍需的诊断能力转入 Web/service 后删除 CLI 公共入口。

验收：源码不再命中 PySide6、PyInstaller、desktop entry 和旧启动脚本；普通安装不下载桌面依赖；Web、launcher 和核心回归测试全部通过。

#### 阶段 6：发布和文档

CI 执行 Python 3.12 测试、wheel/sdist 构建、干净环境安装、包资源 smoke test 和 launcher smoke test；通过 Trusted Publishing 发布 PyPI。README 首页只保留两步安装和启动，迁移与开发说明留在本文件。

### 7.4 回归与回滚策略

- 核心纯函数、SQLite 契约、服务集成、发行物 smoke test 四层测试必须持续存在。
- Feishu 使用 fake client 做 CI 测试；真实 Base 验收覆盖首次创建、幂等运行、状态回拉、部分失败重试和 schema 漂移。
- 每次 schema 变化先备份；迁移复制而非移动；失败可重新执行。
- Web 与旧 CLI 并行到阶段 4 完成；阶段 5 的删除独立提交，整体可 revert。
- PyPI 发布保留上一版本，出现问题时回退版本而不是回滚用户数据库。

### 7.5 低风险优先项

优先补契约测试、引入 AppPaths、修复 seed 的 wheel 打包、抽取 Feishu sync service、将本文件纳入版本控制，再建设 WebUI。不要在新入口验收前同时重写爬虫、匹配规则、数据库和 UI，也不要提前删除桌面或 CLI 回退路径。

## 8. 实施记录

- 阶段 0 已完成：新增详情变化重匹配、飞书创建回执不足的回归测试，并修复后者；测试从 175 项增加到 177 项。
- 阶段 1 已完成：新增 `AppPaths`、LocalAppData 路径模型、包内 seed 资源和 setuptools package-data；wheel smoke test 已验证 seed 随包发布；测试达到 180 项。
- 阶段 2 已开始：Feishu 同步已抽到 `services/synchronization.py`，旧 CLI 保留兼容适配器；daily workflow 和初始化 service 已建立，后续应继续减少 CLI 直接编排。
- 阶段 3 已完成最小纵向切片：WebUI 提供偏好、凭据脱敏、健康检查、岗位列表、后台 daily 任务和工作台预览/初始化 API；页面位于 `web/templates/index.html`。
- 阶段 4 已完成 launcher 基础：自动选择端口、可选打开浏览器、显式数据目录测试；console script 和 `__main__` 已指向 launcher。
- 阶段 5 已完成发行路径切换：桌面 GUI、PyInstaller spec、三个批处理入口、示例 YAML 和桌面依赖已删除；旧 `cli.py` 仅作为迁移期开发兼容模块保留。
- 阶段 6 已完成 CI 配置草案：测试、独立 wheel/sdist 构建、artifact 和 tag 触发 Trusted Publishing；正式发布前仍需在 GitHub 环境配置 PyPI `pypi` environment 和权限。
- 当前验证：全量测试 183 项通过；wheel 包含 `job_monitor/resources/jobs_seed.sqlite`，不包含桌面模块。
