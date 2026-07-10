# Feishu Job Radar（飞书求职雷达）

Feishu Job Radar 是面向个人求职者的本地岗位发现工具。它从 WonderCV 获取公开招聘信息，按你的届别、岗位方向和城市偏好筛选推荐，并把需要处理的岗位同步到你自己的飞书多维表格。

项目在本地运行，不提供 SaaS 服务。飞书负责展示推荐岗位和保存你的求职状态，本地 SQLite 保存抓取、匹配和同步信息。

## 你会得到什么

首次初始化会在你指定的飞书多维表格中自动创建“求职工作台”，包括：

- “待处理”视图：集中处理新推荐；
- “收藏”视图：保留准备投递的岗位；
- “投递进度”看板：跟踪已投递、笔试、面试、Offer 等阶段；
- 岗位、公司、城市、推荐理由、投递入口、截止时间等字段。

程序不会要求你手工维护字段、视图、内部关键词库或 Table ID，也不会覆盖你在飞书填写的求职状态、下次行动和备注。

## 支持环境

- 主要支持：Windows 10/11，Python 3.11 或 3.12；
- CI 兼容验证：Ubuntu + Python 3.11；
- macOS 理论上可运行，但当前没有专项验收。

## 安装

```powershell
git clone <repository-url>
cd feishu-job-radar
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

安装后可以使用任一种入口：

```powershell
python -m job_monitor --help
feishu-job-radar --help
```

## 准备飞书

### 1. 创建企业自建应用

在[飞书开放平台](https://open.feishu.cn/)创建企业自建应用，获得 App ID 和 App Secret，并发布一个可用版本。

为应用开通多维表格所需的读取和管理权限，至少覆盖：

- 获取多维表格信息；
- 新增、更新、删除数据表、字段和视图；
- 查询、新增和更新记录。

### 2. 准备一个 Base

在飞书中创建或打开一个多维表格。这个 Base 可以保留飞书自动创建的空白默认数据表，程序会在其中新增专用的“求职工作台”。

通过多维表格右上角的“更多 → 添加文档应用”，把刚创建的应用加入并授予可管理权限。只给应用开放 API 权限但没有把它加入当前文档，通常会得到 `1254302` 权限错误。

复制浏览器地址栏中的链接。首版只支持：

```text
https://你的租户.feishu.cn/base/...
```

如果链接包含 `/wiki/`，请在飞书中打开原始多维表格后再复制 `/base/` 链接。

## 首次使用

运行：

```powershell
python -m job_monitor init
```

缺少配置时，向导会询问：

- 毕业届别、招聘批次和岗位方向；
- 可选的目标城市和重点公司；
- Base 链接；
- App ID 和 App Secret。

程序先执行只读连接检查并显示变更预览。确认后依次完成：

1. 创建或修复“求职工作台”；
2. 回读字段和视图，确认结构可用；
3. 执行首次岗位扫描和匹配；
4. 把推荐岗位同步为“待处理”；
5. 输出新建、更新、跳过、失败数量和工作台链接。

在无人值守环境中，完整配置后可显式跳过二次确认：

```powershell
python -m job_monitor init --yes
```

`--yes` 不会跳过配置、权限或工作台结构检查。

## 日常使用

每日扫描、回收飞书状态并增量同步：

```powershell
python -m job_monitor daily
```

Windows 用户也可以运行 `run_daily.bat`。

修改偏好后重新匹配已有岗位：

```powershell
python -m job_monitor rematch
```

仅导出本地候选到 Excel：

```powershell
python -m job_monitor export --table all --output data/exports/all_jobs.xlsx
```

`pull` 和 `check` 是排障用的高级命令，可通过 `--help` 查看。

## 配置与凭据安全

向导把配置写入根目录的 `config.yaml`。该文件已被 Git 忽略，不应上传、发送或提交。

- App Secret 只用于获取临时访问凭证；
- 临时 tenant token 不写入配置；
- 日志不应出现完整密钥、token 或 webhook；
- `config.example.yaml` 不包含真实凭据；
- 群机器人 webhook 是可选项，不影响工作台主流程。

## 常见问题

### `1254302 RolePermNotAllow`

应用能读取部分信息不代表能管理工作台。确认应用已经发布、权限已开通，并已作为文档应用加入目标 Base 且拥有可管理权限。

### 提示只支持 Base 链接

不要粘贴 `/wiki/` 链接。在飞书中进入原始多维表格，复制 `/base/` 地址。

### 初始化中断

直接重新运行 `python -m job_monitor init`。程序会使用本地保存的工作台 ID 修复缺失结构，不会重复创建字段、视图或岗位记录。

### 同步部分失败

命令会返回非零退出码，并在摘要中显示失败数量。保留日志后重试；限流和短暂写冲突会自动退避，权限或字段冲突需要先按错误提示修复。

### 不想调用飞书

日常或重新匹配时可使用 `--no-feishu`，数据仍会写入本地 SQLite。

## 数据来源与限制

- 当前主要来源是 WonderCV 公开页面；页面结构变化可能导致解析异常；
- 推荐规则用于减少筛选工作，不保证岗位完全匹配；
- 投递入口优先使用已识别的企业页面，无法确认时回退到来源详情；
- 岗位内容、截止时间和链接可能发生变化，投递前请以企业官方招聘信息为准；
- 项目不上传你的求职状态，飞书和本地文件的数据安全由你自己的账号、设备和权限配置负责。

## 开发验证

```powershell
python -m pip install -e . pytest
python -m pytest -q
```

项目使用 MIT License。
