# Feishu Job Radar

Feishu Job Radar 是一个本地运行的 WebUI 求职工具：浏览器负责交互，Python 负责抓取 WonderCV、匹配岗位、保存 SQLite 数据并同步飞书工作台。

## 当前可验证的安装与启动方式

项目尚未发布到 PyPI。当前请从源码构建并安装：

```powershell
git clone <repository-url>
cd feishu-job-radar
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
.\.venv\Scripts\feishu-job-radar.exe
```

程序会启动本地网页并尝试打开浏览器。需要禁止自动打开浏览器时可增加 `--no-browser`。

发布到 PyPI 并完成发布验收后，计划支持：

```powershell
uvx --python 3.12 feishu-job-radar
```

上述 `uvx` 命令目前不是可用的安装方式。

首次使用按页面完成三步：

1. 选择毕业届别、招聘批次、岗位方向和城市；
2. 填写飞书 Base 链接、App ID 和 App Secret；
3. 预览并创建“求职工作台”。

WebUI 当前使用以下本地用户数据目录保存配置和岗位数据库：

```text
%LOCALAPPDATA%\FeishuJobRadar\
```

程序也会在该目录预留 `logs`、`exports` 和 `backups` 子目录，但当前 WebUI 流程不保证生成日志、导出或备份文件。

App Secret 不会由配置读取接口返回，但当前仍以明文保存在本机 `config.yaml` 中。请保护该文件及本机账户。

## 功能

- WonderCV 列表和详情抓取；
- 按届别、批次、城市、岗位方向和重点公司匹配；
- SQLite 去重、增量扫描、推荐历史和用户状态；
- 自动创建或修复飞书字段、视图和求职工作台；
- 飞书工作台初始化和岗位同步；
- 本地配置、数据库和岗位数量检查。

## 数据迁移

从旧版项目根目录启动时，程序会检查该当前目录中的 `config.yaml` 和 `data\jobs.sqlite`。目标用户目录没有对应文件时，程序会自动复制并校验 SQLite 完整性；旧文件不会被移动或删除。程序不会搜索其他目录，也不会在复制前显示确认页面，因此操作前请自行备份旧数据。

## 开发与测试

开发架构、阶段性重构计划、迁移规则、测试策略和发布流程见 [DEVELOPER.md](DEVELOPER.md)。

运行测试：

```powershell
python -m pip install -e ".[test]"
python -m pytest -q
```

构建发行包：

```powershell
python -m pip install build
python -m build
python scripts/verify_wheel.py dist/*.whl
```

项目使用 MIT License。
