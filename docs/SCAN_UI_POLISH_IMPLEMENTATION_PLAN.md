# JobPicky 扫描与首次设置 UI 第二轮精修实施计划

> 状态：方案已确认，尚未开始代码实现
>
> 建立日期：2026-07-18
>
> 当前分支：`codex/ui-liquid-glass-redesign`
>
> 首轮基线提交：`675b2c6 feat(ui): add liquid glass redesign and fallbacks`
>
> 首轮测试提交：`97339e4 test(ui): cover liquid glass assets and fallbacks`
>
> 上位文档：[`LIQUID_GLASS_UI_REDESIGN_PLAN.md`](./LIQUID_GLASS_UI_REDESIGN_PLAN.md)
>
> 工作流：[`UI_WORKFLOW.md`](./UI_WORKFLOW.md)

## 1. 文档用途

本文记录 Liquid Glass 首轮落地后的第二轮局部精修目标、技术边界、代码修改顺序、Git 管理方式和验收标准，供后续对话直接接力实施。

接手者开始工作前必须依次完整阅读：

1. 仓库根目录 `AGENTS.md`；
2. `docs/UI_WORKFLOW.md`；
3. `docs/LIQUID_GLASS_UI_REDESIGN_PLAN.md`；
4. 本文；
5. 本文第 8 节列出的直接相关代码段与测试。

本文只规划第二轮精修，不重新定义首轮已经确认的整体视觉方向。

## 2. 当前基线

### 2.1 已确认状态

- 首轮 Liquid Glass 换肤已经落地，业务行为正常；
- 当前工作树在制定本文时为 clean；
- 当前 UI 的冷银灰环境、浅蓝磨砂玻璃、白色高亮玻璃和岗位雷达主体继续保留；
- 现有 FastAPI API、扫描任务、偏好数据结构、Hash 路由和 Wheel 打包方式继续保留；
- 首轮自动测试记录为相关测试 13 项通过、全量测试 312 项通过、发布检查 9/9 通过；
- 第二轮尚未执行代码修改和真实渲染验收。

### 2.2 本轮 Design Read

第二轮是一轮可回滚的局部精修：让玻璃材质承担状态表达，修复扫描布局抖动，替换旧式圆形进度语言，并清理聚焦度与首次设置操作区的视觉瑕疵。

### 2.3 主要问题

1. 首次设置未完成时，保存按钮虽然隐藏，但空的浅蓝玻璃操作横幅仍然存在；完成后又出现“浅蓝玻璃套深蓝按钮”的双重表面。
2. 扫描卡片内部使用动态垂直居中和多轮 CSS 覆盖；实时动态逐渐增加时，标题区域会发生位置变化。
3. 当前扫描 loader 是普通圆轨道加蓝点旋转，与新的玻璃材质和岗位雷达语义不匹配。
4. 四个扫描阶段仍是传统数字圆圈步骤条，集中在左栏上半部分，视觉密度和空间分配不合理。
5. 聚焦度的定位包装层被错误赋予整块玻璃背景，形成横向灰色穿模。
6. “偏好信息较完整，雷达信号清晰。”等说明文案与标签、百分比和刻度重复。
7. `app.css` 中扫描工作区存在多轮后置覆盖，继续追加补丁会增加回归风险。

## 3. 核心目标

- 首次设置只有在四个步骤全部确认后才出现最终操作区；最终按钮本身就是浅蓝高亮磨砂玻璃。
- 扫描期间标题、说明、停止按钮和内容分隔位置保持稳定，不受实时动态条数影响。
- 使用轻量数学曲线粒子表现“岗位雷达正在扫描”，不再使用普通圆形 spinner。
- 四个阶段在左栏可用高度内均匀分布，当前阶段使用白色高亮玻璃、呼吸和克制流光表达。
- 修复偏好聚焦度灰色横条，只保留胶囊、刻度圆角矩形和数字浮标各自边界。
- 删除无决策价值的聚焦度说明句。
- 不改变扫描、取消、保存、轮询、状态切换和错误处理行为。
- 不新增前端运行时依赖，不迁移框架，不引入 GSAP。

## 4. 必须保留的产品行为

- 首次设置仍按 `stage`、`roles`、`cities`、`keywords` 四步完成；
- “补充信号”仍为可跳过步骤，但用户必须明确点击完成配置；
- 最终提交前仍执行现有 `validDraft()` 校验；
- 创建雷达后仍保存偏好、进入 `#radar`、加载岗位并开始扫描；
- 编辑偏好仍保留取消、保存、重新匹配和差异摘要；
- 扫描状态仍由现有任务 API 和一秒轮询驱动；
- 停止扫描按钮、终态对勾、实时动态、运行时长和失败路径保持可用；
- 首页岗位雷达仍可进入偏好编辑；
- 所有现有 ARIA、键盘焦点、减少动画和降低透明度降级不得回归；
- 不修改 API 路径、请求体、字段名、任务阶段计算或扫描业务文案。

## 5. 明确不做的事项

- 不重写首页、岗位列表、详情抽屉或集成页；
- 不调整匹配算法、聚焦度计算公式或扫描阶段含义；
- 不复制 `math-curve-loaders` 的源代码；该仓库仅作为数学曲线与粒子尾迹的视觉参考；
- 不把 `liquid-glass-react` 或 React 组件引入当前原生项目；
- 不新增 GSAP、Motion、Canvas 库、图标库或 CSS 框架；
- 不为这次修改创建通用动画框架、组件工厂或新的设计系统；
- 不给多个步骤同时添加持续动画；
- 不用 `!important`、任意超大 `z-index` 或更高选择器权重掩盖根因；
- 不在 CSS 文件末尾继续叠加另一组完整扫描样式；应整理或替换现有重复规则；
- 不改写本轮未涉及的业务文案。

## 6. 已确认的设计与技术决策

### 6.1 首次设置最终操作区

采用“未完成时隐藏整个操作区，完成时显示”的方案。

- `ready = STEPS.every(step => stepComplete(step))` 继续作为唯一就绪判断；
- 首次设置且 `ready === false` 时，`.builder-actions` 整体进入 `hidden`；
- 首次设置完成后，操作区通过 `opacity` 和 `transform` 做一次轻微进入；
- `#save-builder` 在首次设置模式下占满操作区宽度，成为约 64-72px 高的浅蓝高亮玻璃按钮；
- 移除首次设置模式下外层玻璃横幅和内部深蓝按钮的嵌套感；
- 按钮文字保持“创建岗位雷达并开始扫描”；
- loading、disabled、`:hover`、`:active` 和 `:focus-visible` 状态必须清楚；
- 编辑模式继续使用紧凑操作区，不强制全宽 CTA。

不采用长期显示 disabled 横幅，因为当前流程已经有逐步完成提示，空的底部表面会分散注意力。

### 6.2 扫描卡片固定骨架

桌面扫描卡片使用两行骨架：

```text
task-panel
├─ task-heading：固定在顶部
└─ task-body：填充剩余高度
   ├─ task-progress：四个等高阶段
   └─ task-activity：固定可视窗口，内部替换日志
```

实现约束：

- `.task-panel.task-workspace` 不再使用 `justify-content:center`；
- 使用 grid 或顶部对齐的 flex，标题位置由固定内边距决定；
- `.task-heading` 高度允许文案截断，但不能因日志数量变化而移动；
- `.task-body` 使用 `minmax(0, 1fr)` 占据剩余高度；
- `.task-activity-stream` 使用确定的可视高度或 `block-size:100%`，不能只依赖 `min-height`；
- 日志继续在固定窗口内部进入、上移和退出，不增加外层卡片高度；
- 左右卡片可以继续等高，但左卡内部几何不得重新居中；
- 移动端恢复自然高度，不强制桌面等高和大面积空白。

### 6.3 数学曲线扫描 loader

推荐实现一个仅用于扫描标题的内联 SVG 曲线 loader：

- 视觉参考：`Paidax01/math-curve-loaders` 的数学曲线与粒子尾迹；
- 曲线采用自行生成的玫瑰线或 hypotrochoid，不复制上游代码；
- 使用 12-16 个 SVG 粒子，尺寸随尾迹递减；
- 颜色限制为白色、冰蓝和低饱和钴蓝；
- loader 维持当前约 50px 的视觉占位，避免标题重新排版；
- 扫描终态仍替换为现有对勾图标；
- 默认只存在一个动画实例；
- 仅在任务为运行状态、文档可见且未启用减少动画时执行；
- `visibilitychange`、任务终止和面板重建时暂停或取消 RAF；
- 每帧只写 SVG 的 `transform` 或粒子坐标，不读取布局；
- 如果 12-16 粒子版本在目标设备上出现明显抖动，降级为单路径 `stroke-dashoffset + transform` 的纯 CSS 版本；
- `prefers-reduced-motion: reduce` 下显示静态曲线和一个高亮点，不持续旋转。

不引入 GSAP：本轮没有时间线、滚动联动、反转、seek 或复杂编排，CSS 与局部 RAF 已能覆盖需求。

### 6.4 四阶段扫描状态

- `.task-progress ol` 在桌面使用四个等高行；
- 移除数字圆圈和纵向连接线；
- 阶段名称字号提高到约 16-18px；
- pending：透明背景、低对比文字；
- done：正文可读但降低强调，可保留一个非圆形的小对勾；
- current：整行白色高亮磨砂圆角矩形；
- 当前项允许约 `1 → 1.015 → 1` 的轻微呼吸，周期约 2.8-3.2 秒；
- 当前项边缘允许单个顺时针 `conic-gradient` 流光，周期约 8-10 秒；
- 流光由伪元素和 mask 形成 1px 左右边缘，不覆盖正文，不制造霓虹外发光；
- 只给当前项设置 `will-change: transform`；阶段切换后立即移除旧项的持续动画；
- 不支持 mask 时降级为稳定的白色高亮边框；
- reduced-motion 下关闭呼吸、旋转流光和阶段切换位移，只保留静态高亮；
- 移动端使用紧凑两列或一列布局，按实测宽度选择；不得出现横向滚动和文字截断。

### 6.5 聚焦度穿模与说明文案

- `.focus-scale` 只作为数字浮标定位层，保持背景透明；
- 将玻璃背景、边框和内阴影限定在 `.focus-ticks`；
- `.focus-label` 保持独立白色数字浮标；
- 浮标尖角与刻度容器之间保留视觉间隙；
- 不通过提高 `z-index` 掩盖横向灰条；
- `renderRadarMeta()` 不再生成 `focus.note` 的 `<p>`；
- 保留“偏好聚焦度”、等级名称、百分比和刻度的可访问名称；
- 暂不修改 `focusScore()` 的返回结构，除非确认 `note` 没有其他调用者且删除能实际减少代码；
- 修改前必须使用 `rg "focus\.note|note:"` 确认调用范围。

## 7. 动画预算与性能边界

### 7.1 允许的持续动画

扫描期间最多同时存在：

1. 一个标题数学曲线 loader；
2. 一个当前阶段的缓慢呼吸；
3. 一个当前阶段的缓慢边缘流光；
4. 现有实时动态行的短时进入/退出动画。

岗位雷达自身已有的扫描呼吸可以保留，但实施时需观察是否与新 loader 和阶段流光竞争注意力；若竞争明显，优先降低岗位雷达呼吸强度，而不是增加更多动画。

### 7.2 性能规则

- CSS 动画只操作 `transform` 和 `opacity`；
- 不动画 `width`、`height`、`top`、`left`、`padding` 或 `margin`；
- RAF 内不读取 `offset*`、`client*` 或 `getBoundingClientRect()`；
- 数学曲线的静态采样数据在初始化时生成一次；
- 不为每个粒子创建独立 RAF；
- 页面隐藏、扫描停止、路由离开或 reduced-motion 开启时停止 RAF；
- 不给所有阶段或所有粒子盲目设置 `will-change`；
- 日志 FLIP 动画现有的布局读取与写入顺序需要保留或整理，避免交错读写；
- Chrome/Edge 完整效果以流畅为准，Firefox/Safari 降级仍需可读可操作。

## 8. 预计代码修改

### 8.1 `src/jobpicky/web/static/js/app.js`

预计修改：

- `renderBuilder()`：同步整个 `.builder-actions` 的首次设置可见状态；
- `ensureTaskPanel()`：把旧圆形 loader 标记替换为内联数学曲线 SVG 容器；
- 新增或内联最小的曲线 loader 初始化、开始、停止逻辑；
- `renderTask()`：根据运行/终态可靠启动或停止 loader，不重复创建实例；
- `applyScanStatus()` 或现有终态路径：确保路由和任务结束后清理动画；
- `renderRadarMeta()`：停止渲染聚焦度说明 `<p>`；
- 必要时为当前阶段设置现有 `current`、`done`、`pending` class，不引入第二套状态模型。

实现前必须检查：

- `taskPhase()`、`renderTask()`、`pollTask()` 和 `applyScanStatus()` 的完整调用链；
- `ensureTaskPanel()` 是否可能在同一页面生命周期内重建；
- `REDUCE_MOTION` 当前是否监听偏好变化；
- 现有 liquid glass 初始化与销毁是否可复用页面可见性处理。

### 8.2 `src/jobpicky/web/static/css/app.css`

预计修改：

- 合并扫描工作区的多轮覆盖为一组最终桌面规则和对应移动端规则；
- 固定 `.task-heading` 与 `.task-body` 的几何结构；
- 固定实时动态窗口高度并保留内部溢出隐藏；
- 把四阶段改成等高行和玻璃当前态；
- 添加当前阶段呼吸、流光、mask 降级和 reduced-motion；
- 添加数学曲线 SVG 的尺寸、颜色与粒子外观；
- 删除不再使用的 `.task-spinner`、圆形步骤和连接线样式；
- 添加首次设置 CTA 的模式化样式；
- 确认移动端 760px 和 480px 规则不被桌面固定高度污染。

要求：优先删除、替换旧规则，不在文件末尾追加另一套完整覆盖。

### 8.3 `src/jobpicky/web/static/css/liquid-glass.css`

预计修改：

- 移除 `.focus-scale` 上不应存在的玻璃背景和阴影；
- 将对应材质限定到 `.focus-ticks`；
- 为首次设置最终 CTA 复用现有高亮玻璃颜色、内高光、模糊和实色降级；
- 保持 `prefers-reduced-transparency` 和 `data-glass="fallback"` 可读。

### 8.4 `src/jobpicky/web/templates/index.html`

默认不修改。扫描面板当前由 `ensureTaskPanel()` 动态生成，首次设置按钮已有正确语义。

只有以下情况才修改模板：

- 动态字符串中的 SVG 明显损害可维护性；或
- 测试和可访问性要求静态持有 loader 定义。

若无上述必要，按 Ponytail 原则保持模板不变。

### 8.5 测试文件

优先扩展已有 `tests/test_web.py` 或 `tests/test_ui_sandbox.py`，不新建测试框架。

至少覆盖：

- 页面资源仍可加载；
- 扫描面板包含新的曲线 loader 标记，不再依赖旧 `.task-spinner`；
- reduced-motion 和 glass fallback CSS 仍存在；
- 首次设置提交按钮、停止扫描按钮和关键文案仍存在；
- 不改变现有 API 与任务状态断言；
- Wheel 仍包含修改后的 CSS/JS。

静态测试无法证明布局稳定和视觉效果，必须配合第 11 节真实渲染验收。

## 9. 分阶段实施顺序

### 阶段 0：实现前基线

1. `git status --short`；
2. 记录当前分支和最近提交；
3. 运行目标测试；
4. 用隔离 UI 沙盒复现首次设置和扫描中状态；
5. 保存桌面与移动端基线截图到 `.test-results`，不提交截图；
6. 记录标题初始位置和日志铺满后位置。

退出标准：确认基线测试状态，能稳定复现所有六个问题。

### 阶段 1：稳定扫描几何与整理 CSS

1. 合并扫描布局重复规则；
2. 固定标题、内容区和日志窗口；
3. 保留现有 loader 和步骤视觉，先验证结构；
4. 验证 0、1、4、满屏日志时标题位置一致；
5. 运行目标测试。

退出标准：扫描标题不再抖动，桌面和移动端无布局回归。

### 阶段 2：四阶段玻璃状态

1. 去掉数字圆圈与连接线；
2. 将四个阶段均匀分布；
3. 实现 current、done、pending 的玻璃层级；
4. 添加呼吸、流光和静态降级；
5. 检查阶段切换、终态和 reduced-motion。

退出标准：当前阶段一眼可辨，只有当前项持续运动，四项不再拥挤在上方。

### 阶段 3：数学曲线 loader

1. 先实现静态 SVG 曲线和粒子；
2. 加入单一 RAF 运动；
3. 连接扫描运行、终态、页面隐藏和 reduced-motion；
4. 检查重复扫描不会叠加 RAF；
5. 若性能或观感不达标，降级为单路径纯 CSS loader。

退出标准：扫描中表现有岗位雷达辨识度，终态和清理正确，无明显 CPU 占用或掉帧。

### 阶段 4：首次设置 CTA 与聚焦度修复

1. 隐藏未完成时的整个操作区；
2. 将首次设置主按钮改成整块浅蓝玻璃 CTA；
3. 保持编辑模式操作区不变；
4. 修复 `.focus-scale` 穿模；
5. 删除聚焦度说明句；
6. 检查键盘、focus、loading 和 fallback。

退出标准：无空横幅、无深蓝内嵌按钮、无聚焦度灰色横条、无说明句。

### 阶段 5：综合验收与记录

1. 执行第 10 节自动测试；
2. 执行第 11 节视觉、响应式和可访问性验收；
3. 执行发布检查；
4. 更新本文实施记录；
5. 检查 Git 范围与提交历史。

退出标准：所有阻断项通过；非阻断偏差有截图、原因和后续条件。

## 10. 自动测试与命令

### 10.1 开始前与每阶段最小检查

```powershell
git status --short
python -m pytest tests/test_web.py tests/test_ui_sandbox.py -q
```

### 10.2 隔离 UI 环境

```powershell
python scripts/ui_sandbox.py fresh --no-browser
```

需要继续同一隔离数据时：

```powershell
python scripts/ui_sandbox.py continue --no-browser
```

不得使用真实用户 Profile 做 UI 验证。

### 10.3 完整测试

```powershell
python -m pytest -q
```

### 10.4 发布检查

```powershell
python scripts/release_check.py
```

任何失败都必须区分为本轮引入、既有失败或环境缺失；没有证据时不得标记为“无关”。

## 11. 最终验收标准

### 11.1 阻断级功能标准

- [ ] 未完成首次设置时看不到空的底部玻璃操作横幅；
- [ ] 四步全部明确完成后，创建按钮出现且可以提交；
- [ ] 补充信号为空时仍可通过“暂不添加，完成配置”完成流程；
- [ ] 创建雷达后正常进入首页并开始扫描；
- [ ] 编辑偏好仍可取消、保存和重新匹配；
- [ ] 扫描轮询、停止、成功、部分成功、失败和重试行为无回归；
- [ ] 实时动态和运行时长继续更新；
- [ ] 扫描终态 loader 正确停止并显示现有完成语义；
- [ ] 连续启动两次扫描不会产生重复 RAF 或重复动画实例；
- [ ] API、请求体、字段和任务阶段计算未修改；
- [ ] 目标测试、全量测试和发布检查通过，或已有失败被准确记录。

### 11.2 阻断级视觉标准

- [ ] 首次设置 CTA 是一整块浅蓝高亮磨砂玻璃，不再包含深蓝色实心内按钮；
- [ ] 扫描标题在首条日志、四条日志和日志铺满时位置肉眼及测量均稳定；
- [ ] 停止扫描按钮不会因标题或日志变化移动；
- [ ] 四个阶段在左栏高度中均匀分布，没有上挤下空；
- [ ] 当前阶段是白色高亮圆角玻璃矩形，不依赖蓝色数字圆圈表达；
- [ ] 呼吸幅度克制，不造成文字模糊或卡片明显跳动；
- [ ] 流光仅沿边缘缓慢顺时针移动，不覆盖正文，不产生霓虹感；
- [ ] 数学曲线 loader 与雷达材质协调，明显区别于普通 spinner；
- [ ] 聚焦度数字浮标、刻度胶囊与外围卡片边界独立，无横向灰色穿模；
- [ ] “偏好信息较完整，雷达信号清晰。”及同类聚焦度说明句不再显示；
- [ ] 没有新增玻璃套玻璃、多重边框或无语义发光。

标题稳定性推荐增加一个可重复的测量标准：日志从最少状态增长到填满可视窗口时，`.task-heading` 的 `getBoundingClientRect().top` 差值不超过 1px。

### 11.3 响应式标准

至少检查：

- 桌面：`1440 × 900`；
- 紧凑桌面：`1366 × 768`；
- 移动端：`390 × 844`；
- 窄移动端：`360 × 800`。

所有宽度必须满足：

- [ ] 无页面级横向滚动；
- [ ] 标题、停止按钮、阶段名称和日志不互相覆盖；
- [ ] 主要按钮文字不换行；
- [ ] 移动端不强制桌面等高，不出现大块无意义空白；
- [ ] 四阶段在移动端使用一列或紧凑两列，文字完整可读；
- [ ] 雷达卡片不挤压扫描主任务；
- [ ] 软键盘和安全区下首次设置 CTA 仍可到达。

### 11.4 可访问性标准

- [ ] 首次设置 CTA 和停止扫描按钮有清晰 `:focus-visible`；
- [ ] 键盘可以完成四步设置、创建雷达和停止扫描；
- [ ] current、done、pending 不只依赖颜色区分；
- [ ] loader 为装饰性 SVG 时使用 `aria-hidden="true"`，状态文字继续由可读文本提供；
- [ ] 运行时长使用等宽数字且更新不会抢夺焦点；
- [ ] `prefers-reduced-motion: reduce` 下无持续旋转、呼吸、流光和日志位移动画；
- [ ] reduced-motion 下仍能从静态高亮识别当前阶段和扫描状态；
- [ ] `prefers-reduced-transparency` 或 glass fallback 下文字对比度和控件边界清楚；
- [ ] 正文和控件文字达到 WCAG AA；
- [ ] 现有 ARIA、对话框语义和焦点恢复无回归。

### 11.5 性能与实现质量标准

- [ ] 不新增运行时依赖；
- [ ] 同一时间最多一个数学曲线 RAF；
- [ ] RAF 在页面隐藏、扫描结束和 reduced-motion 下停止；
- [ ] RAF 每帧不读取布局；
- [ ] 持续 CSS 动画只作用于当前阶段；
- [ ] 不动画布局属性；
- [ ] 无 `!important`、任意超大 `z-index` 或新的大块重复覆盖；
- [ ] 旧 `.task-spinner`、圆形步骤和连接线的失效样式被删除；
- [ ] 扫描样式最终定义集中、可追踪，桌面与移动端规则边界清楚；
- [ ] Wheel 继续包含修改后的静态资源；
- [ ] Chrome/Edge 无明显掉帧；Firefox/Safari 降级可读可操作。

### 11.6 Git 与交付标准

- [ ] 工作分支为 `codex/ui-liquid-glass-redesign`，或接力者明确记录了新分支来源；
- [ ] 开始前工作树状态已记录；
- [ ] 每个提交范围单一、可运行、可单独回滚；
- [ ] 没有临时截图、隔离数据、缓存或真实用户数据进入提交；
- [ ] 没有无关格式化和后端业务修改；
- [ ] 最终 `git diff --stat` 与第 8 节预计文件相符；
- [ ] 本文实施记录填写实际提交、文件、测试、截图尺寸和偏差；
- [ ] 未经用户要求不推送、不创建 PR、不修改发布版本。

## 12. Git 管理方案

### 12.1 开始实施前

```powershell
git status --short
git branch --show-current
git log -5 --oneline --decorate
```

如果当前分支仍为 `codex/ui-liquid-glass-redesign` 且工作树干净，直接继续该分支。不要为了第二轮机械创建新分支。

如果存在用户未提交修改：

- 先查看 `git status --short`；
- 再查看相关文件的 `git diff --stat`；
- 只读取与本轮重叠的指定文件差异；
- 不覆盖、不 reset、不 checkout 用户修改；
- 无法安全隔离时停止并请求用户决定。

### 12.2 推荐提交拆分

建议保持 3-4 个提交：

1. `docs(ui): plan scan workspace polish`
2. `fix(ui): stabilize scan workspace geometry`
3. `style(ui): refine scan progress and curve loader`
4. `style(ui): polish onboarding action and radar focus meter`
5. `test(ui): cover scan polish states and fallbacks`

实施时可将 4 和 5 合并，但不得把几何修复与大段视觉动画混成一个难以回滚的提交。

### 12.3 暂存与检查

每次只暂存当前阶段文件。例如：

```powershell
git add src/jobpicky/web/static/css/app.css src/jobpicky/web/static/js/app.js
git diff --cached --stat
git diff --cached -- src/jobpicky/web/static/css/app.css src/jobpicky/web/static/js/app.js
```

禁止使用 `git add .` 隐藏无关改动。

每次提交前至少执行：

```powershell
git status --short
git diff --stat
python -m pytest tests/test_web.py tests/test_ui_sandbox.py -q
```

### 12.4 推送、PR 与回滚

- 未经用户明确要求不推送或创建 PR；
- 如果需要推送，保持 `codex/` 分支前缀；
- PR 描述引用本文，列出布局稳定性、动画降级、测试和浏览器结果；
- 几何修复应可独立保留，即使数学曲线 loader 后续被回滚；
- 若 loader 性能不达标，只回滚 loader 提交，扫描布局和阶段玻璃状态仍应工作；
- 回滚不得删除用户数据、Profile、数据库或配置。

## 13. 视觉 QA 方式

- 优先使用隔离 UI 沙盒，不使用真实用户数据；
- 用户已经提供了首轮首次设置页和扫描页截图，它们是问题基线，但临时剪贴板路径不能作为跨对话持久依赖；
- 实施时应重新生成 `.test-results` 下的本地基线与结果截图；
- 若需要浏览器自动控制，按 `LIQUID_GLASS_UI_REDESIGN_PLAN.md` 约束先向用户说明目的和范围；
- 至少保存首次设置未完成、首次设置完成、扫描首条日志、扫描日志铺满、reduced-motion 和移动端六类画面；
- 截图默认不提交 Git；
- 没有完成真实渲染检查时，不得宣称视觉验收通过。

## 14. 跨对话接力模板

新的执行者开始时应报告：

```text
已完整阅读 AGENTS.md、UI_WORKFLOW.md、LIQUID_GLASS_UI_REDESIGN_PLAN.md 和 SCAN_UI_POLISH_IMPLEMENTATION_PLAN.md。
当前阶段：<0-5 与阶段名称>
当前分支：<分支>
工作树：<clean / 已有修改摘要>
基线提交：675b2c6、97339e4
本轮准备修改：<文件列表>
必须保留：现有 API、四步设置、扫描轮询、停止扫描、实时动态、雷达交互、fallback 与可访问性。
明确不做：框架迁移、新依赖、后端逻辑改造、全站重写。
```

阶段完成后更新：

```text
阶段：<编号与名称>
完成：<实际完成项>
文件：<实际文件>
提交：<提交哈希或未提交原因>
测试：<命令与结果>
视觉检查：<页面、尺寸、状态与结果>
动画检查：<RAF 数量、清理、reduced-motion>
偏差：<与本文不同之处及原因>
下一步：<下一阶段>
```

## 15. 实施记录

### 15.1 当前状态

- 现状审查：完成；
- 第二轮方案：完成；
- 实施计划：完成；
- 代码实现：完成；
- 自动测试：目标测试 13 项通过，全量测试 312 项通过，发布检查 9/9 通过；
- 代码验收：完成 JS 语法、静态资源标记、减少动画、透明度降级、旧样式移除和 Git 范围检查；
- 视觉 QA：按用户要求未使用浏览器控制或自动截图，由用户后续人工执行；
- 当前工作树：实施开始前为 clean，代码和本文记录等待提交。

### 15.2 计划使用的技能

- `redesign-existing-projects`：约束为已有产品渐进式精修；
- `gsap-core`：判断 CSS、RAF 与 GSAP 的适用边界；
- `gsap-performance`：制定 transform、RAF、可见性暂停和 reduced-motion 规则；
- `ponytail full`：限制文件、依赖和抽象，优先删除重复覆盖并复用现有状态模型；
- `docs/UI_WORKFLOW.md`：规定审查、动画预算、最小实现与验证顺序。

### 15.3 实际结果

- 实际开始日期：2026-07-18；
- 实际修改文件：`app.js`、`app.css`、`liquid-glass.css`、`index.html`、`tests/test_web.py` 和本文；
- 实际提交：`170e697 style(ui): polish scan workspace and onboarding`；测试与记录提交见本文件的 Git 历史；
- 目标测试结果：`python -m pytest tests/test_web.py tests/test_ui_sandbox.py -q` 为 13 passed；
- 全量测试结果：`python -m pytest -q` 为 312 passed；
- 发布检查结果：`python scripts/release_check.py` 为 9/9 passed；
- JS 语法结果：`node --check src/jobpicky/web/static/js/app.js` 通过；
- 桌面视觉结果：未执行，交由用户人工验收；
- 移动端视觉结果：未执行，交由用户人工验收；
- reduced-motion / transparency 结果：代码规则与静态测试通过，未执行视觉验收；
- 浏览器兼容结果：未使用浏览器控制功能，待用户人工确认；
- 与计划的偏差：数学曲线 loader 使用原生 SVG `animateMotion`，没有创建 RAF；因此无需 RAF 生命周期管理，且不存在重复 RAF 风险；
- 已知限制：SMIL 动画、流光边缘、模糊强度和四种目标尺寸的实际观感仍需用户确认；
- 最终验收：功能与代码验收通过，视觉验收待用户完成。
