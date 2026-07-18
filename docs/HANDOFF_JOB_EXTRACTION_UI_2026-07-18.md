# JobPicky 岗位抽取与 UI 重设计交接记录

> 更新时间：2026-07-18（Asia/Shanghai）  
> 当前分支：`codex/job-extraction-ui-v3`  
> 状态：实现进行中，功能代码已有较多修改，但尚未完成全量测试、浏览器视觉验收、正式种子数据替换和 Git 提交。

## 1. 文档目的

本文件记录本轮任务的需求拆解、现状分析、设计决策、已经完成的修改、数据审计结论、验证证据和剩余工作。接手者应在当前工作树上继续，不要重新开始，也不要把 `.test-results` 中的候选数据库直接当作已发布的正式数据。

## 2. 用户目标

### 2.1 扫描进度

- 把当前笼统、缺少反馈的扫描流程改成持续可感知的工作流。
- 扫描时展示类似“发现新公司 ×××”“正在获取招聘广告”“正在抓取详情”“正在获取官方投递链接”等动态活动，并显示持续旋转的工作指示器。
- 不再机械展示原来的 3、4、5 等细碎阶段；用户侧只保留少量合乎心智模型的步骤。
- “补全官方投递链接”改成用户能理解的“整理岗位信息”“个性化匹配”等表达。
- 不显示没有价值的“完成通知”，最终状态只需要“完成”。

### 2.2 岗位抽取

- 调查旧报告中 764 条公告、1,419 个结构化岗位、381 条未提取公告的真实原因。
- 必须查看实际网页和当前抽取结果，同时审计抽取失败与抽取成功的样本，关注虚构、遗漏、过长、字段串位和错误切分。
- 修复应保持保守和系统性，不能为单个样本制造新的回归。

### 2.3 首页岗位卡片

- 不显示“2027届”“秋招”等冗余标签；职位卡只保留城市位置标签。
- 公司属性和行业标签继续显示，但不显示秋招批次。
- 粗体主体只显示公司名称，避免重复公司名或把一大段公告标题加粗。
- 使用简短、灰色、接近 WonderCV 列表页的信息摘要，不使用冗长详情正文。

### 2.4 岗位详情

- 招聘类型与招聘批次去重；删除毕业届别、信息来源、信息核验等用户价值较低的字段。
- 学历展示实际出现的最低要求。
- “广告内职位”采用一职位一卡片，只显示职位名称，不展示不可靠的地点和技能推断。
- 摘要使用列表页短摘要，不使用被截断的详情正文；保留“为什么推荐”。
- 详情不再从右侧抽屉弹出，改成首页小卡片自然放大至屏幕中央、悬浮于虚化背景之上。

### 2.5 整体视觉

- 首页、列表卡片和详情卡片统一改成更克制、精致、高级的视觉风格。
- 用户提到可以迁移 Nuxt/React，但这不是强制要求；现状评估后决定保留当前技术栈。

## 3. 工作流与设计决策

前端修改前已完整阅读并遵循 `docs/UI_WORKFLOW.md`。本轮使用并参考了以下技能：

- `design-taste-frontend`
- `redesign-existing-projects`
- `ponytail`
- `gsap-core`
- `gsap-performance`

设计路线为“克制的编辑型求职工作台”：冷白和浅灰为基底，蓝色为状态强调，降低装饰噪声，让公司、摘要、城市和匹配理由形成清晰层级。设计旋钮大致为视觉变化 5、动效 5、信息密度 5。

关键技术决策：

- 保留 FastAPI + 原生 HTML/CSS/JS，不迁移 React/Nuxt。当前需求没有复杂状态管理，迁移只会扩大回归面。
- 不新增 GSAP 依赖；卡片变形使用 Web Animations API，简单状态动效使用 CSS，并支持 `prefers-reduced-motion`。
- 保留现有路由、筛选、配置流程、雷达扫描、飞书能力、数据接口和可访问性语义。
- 后端可继续保留原 6 阶段以兼容既有逻辑，UI 映射为 4 个用户可理解的阶段：获取最新岗位、个性化匹配、整理岗位信息、完成。

## 4. 岗位抽取现状与根因分析

### 4.1 原始正式种子数据

当前正式资源仍未替换：

- `src/jobpicky/resources/jobs_seed.sqlite`
- `src/jobpicky/resources/jobs_seed_source.json`

其统计仍为：

- 764 条招聘公告
- 1,419 个岗位
- 383 条公告有岗位
- 381 条公告没有岗位

`tests/test_seed.py` 仍断言 1,419 个岗位。

### 4.2 已确认的主要根因

1. 旧解析器过度依赖岗位名称后缀白名单，漏掉 `.role-item` 中的真实职位，例如“会计岗”“预培生”“AI算法工程师-大模型”。
2. 详情合并会用长详情正文覆盖列表页短摘要，导致卡片摘要冗长、截断生硬。
3. 学历提取顺序错误，可能优先得到最高学历，而不是最低门槛。
4. 表格解析把“专业要求”“招聘对象”等列误认为职位名称列。
5. 某些 `.role-item` 实际是招聘活动链接、报名人群、人才计划或证书名称，并非岗位。
6. 少量源网页本身存在跨公司拼接或疑似生成错误，不能强行抽取。例如样本 89 和 815。
7. 很多未抽取公告只有时间线、材料要求、考试安排、专业目录或企业介绍，本身没有可验证的岗位名称。

### 4.3 审计覆盖与代表样本

已经对缓存或在线详情页及结果做过多组抽样，包括 740、390、557、247、181、313、750、29、327、368、519、259、688、804、810、733、755、815 等。

代表性结果：

- 740 兴云数科：3 个岗位，最低学历为硕士及以上。
- 390 辽宁能源：6 个岗位，最低学历为本科及以上。
- 519 迈瑞：稳定抽取 12 个岗位。
- 259 清华同衡：10 个清洗后的岗位，没有把专业要求列当岗位。
- 163 深圳燃气：保留 7 个真实方向类别。
- 804 广西农投：只保留“总部管培生”，不再把报名资格当岗位。
- 688：中国铁路类公告链接，不构造岗位，保持为空。
- 733：页面内容是报名人群/证书名称，保持为空。
- 815：来源疑似跨公司污染，保守保持为空。
- 89：跨公告混合内容，保持为空。

候选结果仍有 197 条空公告：

- 45 条提到附件、岗位表或报名材料。
- 27 条含表格，已经人工抽样确认主要是时间线、材料、考试环节、专业或企业数据，不是岗位名称表。
- 13 条有 role card，但按保守规则拒绝。
- 1 条明确跨公告混合（样本 89）。
- 160 条是普通或泛化页面，没有可用 role card/岗位表；分类信号之间有重叠，因此数量不可简单相加。

早期曾用宽泛关键词/页面图像信号分类，197 条全部命中，但主要受页脚和通用文案干扰，该结果没有分析价值，不应写入正式结论。

## 5. 已完成的代码修改

### 5.1 抽取与数据

`src/jobpicky/wondercv.py`

- 引入 BeautifulSoup 进行结构化页面解析。
- 抽取版本升级为 `detail-structure-v3`，岗位版本升级为 `position-v3`。
- 新增 `extract_wondercv_card_summary` 和 96 字以内的短摘要逻辑。
- 合并详情时保留列表页短摘要，不再用长详情覆盖。
- 优先解析权威 `.role-item` 和岗位表，之后才走启发式回退。
- 严格限制表格岗位列，支持“岗位方向”，排除“专业要求”“招聘对象”等字段。
- 清理岗位代码、城市、薪资、批次/届别和过长括号方向。
- 拒绝招聘活动、报名人群、人才计划和跨公司混合公告。
- 对招聘活动页 role card 采用标题证据约束，只保留能被前置 h2/h3 标题佐证的岗位。
- 支持把部门实习方向展开成明确职位。
- 去重并处理重复“岗”后缀。
- 学历按大专、本科、硕士、博士的低到高顺序提取最低要求。
- 更新抓取进度文案，加入公司、广告、详情等实时动作。

`scripts/upgrade_seed_online.py`

- 在合并详情前从发现页恢复短摘要，避免历史长摘要继续污染候选种子。

`src/jobpicky/storage.py`

- 内部查询带出 `raw_title`，供服务层形成更合理的卡片数据。

`src/jobpicky/services/web_state.py`

- API 新增 `card_summary`。
- 对外响应移除 `raw_title`。
- 摘要缺失时提供保守回退。

### 5.2 扫描进度

`src/jobpicky/web/app.py`

- `TaskManager` 记录最近 6 条去重活动，字段包括文本、阶段、步骤、状态和时间。

`src/jobpicky/services/scanning.py`

- 通过属性注入爬虫进度回调，避免破坏既有测试替身的构造参数。
- 官方链接补全过程能够上报细粒度进度。
- 修复一处抓取错误信息乱码。

`src/jobpicky/pipeline.py`

- 官方链接补全支持可选进度回调，并按公司上报查找过程。

`src/jobpicky/services/local.py`

- 增加 reporter 回退和任务初始进度基线。

### 5.3 UI 与交互

`src/jobpicky/web/templates/index.html`

- 静态资源缓存版本更新为 `20260717-4`。
- 右侧 drawer 改为具备语义和可访问性的居中模态层/背景层结构。

`src/jobpicky/web/static/js/app.js`

- 岗位卡只保留公司属性/行业、粗体公司名、短摘要、单一城市标签和必要的日期/截止提示。
- 移除秋招、届别、学历和推荐理由等列表卡噪声。
- 详情改为居中卡片变形动画，加入背景虚化、焦点陷阱、Escape 关闭、背景 inert 和 reduced-motion 支持。
- 详情事实区只保留城市、招聘类型、最低学历、公司性质、行业和截止日期。
- 岗位列表改为标题单卡，不展示地点/技能推断。
- 保留“为什么推荐”和原文/投递入口。
- 扫描页映射成 4 个用户阶段，加入 spinner、活动流、最新活动动效和耗时展示。

`src/jobpicky/web/static/css/app.css`

- 完成冷白/浅灰/蓝色的整体视觉重设计。
- 重做列表卡、扫描面板、居中详情层、背景虚化、响应式和 reduced-motion 样式。
- 已针对旧样式残留补充选择器优先级修复，但仍需要浏览器视觉验收。

### 5.4 测试修改

`tests/test_wondercv.py`

- 扩展到 29 个测试，覆盖 role card、岗位表列、跨公司污染、活动页证据、代码/批次/城市/薪资清洗、部门方向展开、摘要保留和截断。

`tests/test_web.py`

- 增加短摘要 API、`raw_title` 不泄露和任务活动历史测试。

## 6. 候选数据与验证结果

候选数据库位置：

`.test-results/seed-upgrade/jobs_seed_final.sqlite`

当前候选统计：

- 764 条公告
- 2,299 个岗位
- 567 条公告有岗位
- 197 条公告无岗位
- 相比旧数据恢复 187 条原本无岗位的公告
- 有 3 条原本“有岗位”的公告被修正为空：534、733、815，原因分别是活动标题、报名人群/证书、污染来源
- 重复岗位标题：0
- 超过 60 字的岗位标题：0
- 按现有审计规则识别的公告名、资格、代码、薪资类可疑岗位：0
- 超过 96 字的摘要：0
- SQLite integrity check：通过
- 外键错误：0

注意：候选数据库最后有 366 行摘要通过辅助逻辑直接在临时库更新。正式发布前必须通过脚本导出、重建和统计比对验证其可复现性。

缓存页面位于 `.test-results/seed-upgrade/html-cache`，约 802 页、65 MB。正式数据构建和审计完成前不要删除。

已通过的验证：

- `tests/test_wondercv.py`：29 passed。
- 一组 daily/web/local 兼容测试：29 passed。
- 新增 web 定向测试：2 passed。
- `node --check src/jobpicky/web/static/js/app.js`：通过。
- 可见 HTML/JS/CSS 中长破折号 `—/–` 搜索无命中。

曾出现但已修复的问题：混合测试最初有 16 个失败，原因是把 progress callback 作为爬虫构造参数传入，以及误删 collected date；随后已改为属性注入并恢复日期逻辑。

尚未完成：最新代码下的完整相关测试、全量 pytest、浏览器视觉 QA、正式种子替换和可复现性验证。

## 7. 接手后必须按顺序完成的工作

### 第一步：修复运行时列表摘要遗漏

检查 `src/jobpicky/wondercv.py` 列表卡解析区域（此前约 86–119 行）。当前构造对象处仍可能是：

```python
summary=parsed["summary"]
```

应改为调用 `_concise_card_summary(...)` 或等价的统一短摘要入口。否则种子升级脚本虽会修正摘要，正常在线抓取仍可能保存长摘要。修改后补回归测试。

### 第二步：测试

先运行相关套件：

```powershell
python -m pytest tests/test_wondercv.py tests/test_web.py tests/test_daily_workflow.py tests/test_official_pipeline.py tests/test_local_application_service.py tests/test_seed_upgrade_online.py -q
node --check src/jobpicky/web/static/js/app.js
```

再运行全量测试：

```powershell
python -m pytest -q
```

如有失败，应优先判断是本轮回归、正式种子仍旧导致的预期值差异，还是既有环境问题，不要直接放宽测试。

### 第三步：生成并发布正式种子

如第一步改变了解析结果，建议使用现有缓存重新完整构建候选库。确认候选统计和审计结果后：

```powershell
python scripts/export_seed_source.py --database .test-results/seed-upgrade/jobs_seed_final.sqlite --output .test-results/seed-upgrade/jobs_seed_source_final.json
```

然后：

1. 用验证后的候选库替换 `src/jobpicky/resources/jobs_seed.sqlite`。
2. 用导出的 JSON 替换 `src/jobpicky/resources/jobs_seed_source.json`。
3. 把 `tests/test_seed.py` 的岗位数量期望从 1,419 更新为最终实测值；当前候选是 2,299，但重建后必须重新确认。
4. 从正式 JSON 用 `build_seed.py` 构建一个临时数据库，比较条数、摘要长度、完整性、外键和核心样本，确认资源可复现。

不要覆盖用户位于 `%LOCALAPPDATA%\JobPicky\jobs.sqlite` 的个人数据库；本轮没有触碰该文件。

### 第四步：浏览器视觉 QA

使用浏览器工具前，必须按仓库规则完整读取：

`C:\Users\Administrator\.codex\plugins\cache\openai-bundled\browser\26.715.21425\skills\control-in-app-browser\SKILL.md`

并先在 commentary 中说明使用该技能的原因。随后检查 `tests/test_ui_sandbox.py`，用 `.test-results` 下的隔离 profile 启动，不要使用或污染用户本地 profile。

至少验证：

- 桌面 1440×900 和移动端 390×844。
- 岗位卡默认、hover、键盘 focus。
- 详情打开/关闭、卡片变形、背景虚化、Escape、焦点返回和滚动锁定。
- 运行中与完成后的扫描进度、活动流和耗时。
- `prefers-reduced-motion` 下没有强制动画。
- 长公司名、长职位名、无摘要、无岗位、多个岗位时不破版。

### 第五步：最终数据/UI 核对

- 列表卡不出现“2027届”“秋招”标签。
- 详情不出现信息来源、核验状态、毕业届别或重复批次。
- 最低学历显示正确。
- 岗位子卡只显示岗位名称。
- API 不暴露 `raw_title`，`card_summary` 不超过 96 字。
- 扫描进行中持续有明确反馈，结束只显示“完成”。

### 第六步：Git 收尾

先按仓库规则依次检查：

```powershell
git status --short
git diff --stat
```

然后只审查本任务相关文件的差异。全部验收通过后再提交，建议提交信息：

```text
feat: refine job discovery and extraction
```

除非用户另行要求，不要推送远端或创建 PR。

## 8. 验收标准

任务完成需同时满足：

1. 抽取测试、相关业务测试和全量测试通过；若存在环境性跳过，需明确记录。
2. 正式种子资源已更新，能从源 JSON 可复现构建，数据库完整性和外键检查通过。
3. 岗位数量和 197 条保守空公告的处置有可解释记录，不通过虚构岗位追求覆盖率。
4. 列表卡和详情信息层级符合第 2 节需求，无冗余秋招/届别/来源/核验字段。
5. 详情卡在桌面和移动端视觉正常，动画顺滑，键盘操作和 reduced-motion 可用。
6. 扫描过程提供持续动态活动反馈，不让用户误以为卡死。
7. 不破坏配置、筛选、雷达扫描、飞书和官方投递链接等原有能力。
8. Git 工作树只包含预期修改，并完成一个清晰提交；无需默认推送。

## 9. 当前 Git 与文件状态

当前已有 13 个被修改文件，约 824 行新增、40 行删除，尚未提交：

- `scripts/upgrade_seed_online.py`
- `src/jobpicky/pipeline.py`
- `src/jobpicky/services/local.py`
- `src/jobpicky/services/scanning.py`
- `src/jobpicky/services/web_state.py`
- `src/jobpicky/storage.py`
- `src/jobpicky/web/app.py`
- `src/jobpicky/web/static/css/app.css`
- `src/jobpicky/web/static/js/app.js`
- `src/jobpicky/web/templates/index.html`
- `src/jobpicky/wondercv.py`
- `tests/test_web.py`
- `tests/test_wondercv.py`

本交接文档是新增文件。没有 commit，没有 push，没有 PR。

## 10. 已知风险与注意事项

- `app.js` 中 `showDrawer` 为 async，调用方未显式 await；通常不影响交互，但视觉验收时应检查快速连点和数据加载竞态。
- WAAPI 动画使用 `fill: both`，尚未显式 cancel，需观察重复打开详情是否积累样式或闪烁。
- 新 CSS 主要追加在旧样式之后，并已做局部优先级修复；仍可能存在旧规则覆盖，必须以浏览器实测为准。
- `prefers-reduced-transparency` 支持度不一致，当前应有普通背景回退，但仍需验证。
- `setWorkspaceInert` 会影响 onboarding 和主工作区，验证详情关闭后焦点与交互是否完全恢复。
- 活动页标题证据和跨公告拒绝规则是有意保守的；调整时必须保护已审计样本，避免“提升数量”导致虚构岗位。
- 当前候选库不是正式资源，正式替换前不要对外宣称 2,299 已发布。
- 用户个人数据库没有被修改。抽取版本变更会在后续扫描时触发相应补全逻辑，应验证迁移体验。

## 11. 推荐接手起点

第一条动作应是查看当前状态并定位第 7 节第一步的摘要赋值：

```powershell
git status --short
rg -n "summary=parsed|_concise_card_summary" src/jobpicky/wondercv.py
```

修复该遗漏后，从相关测试开始继续。不要先重做 UI，也不要先覆盖正式种子文件。
