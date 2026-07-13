# Feishu Job Radar 开发须知

本文只记录当前仓库仍然有效的开发约束、容易踩坑的地方和验收命令。产品使用说明以 `README.md` 为准。

## 当前结构

- `src/job_monitor/`：应用源码；使用 `src` layout。
- `tests/`：pytest 测试。
- `scripts/release_check.py`：发布前的干净安装验收入口。
- `pyproject.toml`：依赖、Python 版本、构建和 pytest 配置。
- `src/job_monitor/resources/`：必须随 wheel 发布的资源，例如 seed SQLite 数据库和 WebUI 模板。

项目要求 Python `>=3.11`。应用是本地 WebUI，用户数据默认位于 Windows 的 `%LOCALAPPDATA%\FeishuJobRadar\`；测试可以使用 `FEISHU_JOB_RADAR_HOME` 指向临时目录。

## 必须注意的坑

### 中文和文件编码

- 源码、YAML、Markdown、HTML 和测试文件统一按 UTF-8 处理。读写文件时显式指定 `encoding="utf-8"`，不要依赖 Windows PowerShell 或系统默认编码。
- 终端显示乱码不等于文件已经损坏。先用 UTF-8 编辑器或 Python 读取原始内容确认，不要因为终端显示异常就批量转码无关文件。
- 不要在无关改动中修改现有中文文案、编码形式或测试中的 Unicode 样例；编码修复必须有明确范围并配套测试。
- YAML 写回时保持 Unicode 内容可读，沿用 `config.py` 的 UTF-8 和 `allow_unicode=True` 约定。
- 需要验证中文、YAML 或 HTML 时，检查文件实际字节和解析结果，不要只根据控制台渲染结果判断。

### 配置、数据和密钥

- 不提交真实的 Feishu Base URL、App Secret、运行中的 SQLite、用户配置、日志、导出文件或备份。
- `config.yaml`、`data/`、`dist/`、`build/`、虚拟环境和 `.test-results/` 都是本地或构建产物；确认 `.gitignore` 后再提交。
- `jobs_seed.sqlite` 是仓库内的只读发布资源，不要用用户运行数据覆盖它。
- 测试必须使用临时目录、fake client 或 mock，不访问真实 Feishu 数据，不把凭据写入断言、异常消息或日志。

### 路径和进程

- 不要假设当前工作目录是仓库根目录；应用路径通过 `AppPaths` 管理，测试用 `tmp_path` 或 `FEISHU_JOB_RADAR_HOME` 隔离。
- WebUI 测试必须禁用浏览器自动打开，并在临时端口、临时数据目录中启动服务。
- 修改 launcher、资源打包、依赖或 `pyproject.toml` 后，必须做一次干净 wheel 安装验收；仅通过源码路径运行不能证明安装包正确。
- `release_check.py` 会清理并重新生成 `dist/`，不要在脚本运行期间依赖旧构建产物。

## 测试和验收

### 一次性开发环境准备

```powershell
python -m pip install -e ".[test]"
```

如果只需要运行已有测试，环境准备好后不需要每次重新创建虚拟环境或重新安装项目。

### 日常开发：普通测试

```powershell
python -m pytest -q
```

日常代码修改至少执行这条命令。提交前要求全部测试通过；新增或修改行为时，必须同步维护对应测试。普通测试验证代码逻辑，不验证 wheel 内容、安装依赖或用户机器上的启动路径。

### 发布验收：干净安装测试

```powershell
python scripts/release_check.py
```

以下情况必须执行：

- 修改依赖、`pyproject.toml`、构建配置或资源打包；
- 修改 launcher、WebUI 启动路径或本地数据目录；
- 准备合并、打 tag 或发布 PyPI；
- 修改可能影响安装后导入、静态资源或依赖解析的代码。

脚本会自动构建 wheel/sdist、验证 wheel 内容、创建全新临时虚拟环境、安装 wheel、执行 `pip check`，再从仓库外启动 WebUI，检查首页、`/api/health`、运行目录创建和干净退出。

成功输出应为：

```text
[PASS] Build package
[PASS] Verify wheel
[PASS] Create clean environment
[PASS] Install package
[PASS] Dependency check
[PASS] Launch outside repository
[PASS] WebUI health check
[PASS] Clean shutdown

RESULT: PASS  8/8
```

失败时终端只显示失败阶段、简短原因和日志位置；完整构建、pip 和服务日志位于 `.test-results/release-check.log`。不要把完整日志复制进提交说明或测试断言。

## 提交前检查

```powershell
python -m pytest -q
git diff --check
git status --short
```

如果触发了发布验收条件，再执行：

```powershell
python scripts/release_check.py
```

提交前确认没有凭据、运行数据、临时目录或无关格式化变更。GitHub Actions 的普通测试和发布验收应复用上述入口；不要重新在 workflow 中堆叠独立的 wheel 构建、venv 安装、`pip check` 或 smoke 命令。
