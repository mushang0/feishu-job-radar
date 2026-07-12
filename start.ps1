param([Parameter(ValueFromRemainingArguments = $true)][string[]]$CommandArgs)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot
$PythonExe = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

function Pause-For-User {
    Write-Host ''
    Read-Host '按 Enter 键返回菜单或关闭窗口'
}

function Ensure-Environment {
    if (-not (Test-Path $PythonExe)) {
        Write-Host '正在准备 Python 3.11 虚拟环境，请稍候...'
        & py.exe -3.11 -m venv (Join-Path $ProjectRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw '未找到可用的 Python 3.11。请安装后重新运行 start.bat。' }
    }
    & $PythonExe -c 'import job_monitor' 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host '正在安装项目依赖，请稍候...'
        & $PythonExe -m pip install -e .
        if ($LASTEXITCODE -ne 0) { throw '依赖安装失败。请检查网络连接后重新运行 start.bat。' }
    }
}

function Invoke-Radar([string[]]$Arguments) {
    & $PythonExe -m job_monitor --config (Join-Path $ProjectRoot 'config.yaml') --db (Join-Path $ProjectRoot 'data\jobs.sqlite') @Arguments
    return $LASTEXITCODE
}

try {
    Ensure-Environment
    if ($CommandArgs.Count -gt 0) {
        $exitCode = Invoke-Radar $CommandArgs
        Pause-For-User
        exit $exitCode
    }

    while ($true) {
        Clear-Host
        Write-Host '======================================'
        Write-Host '           飞书求职雷达'
        Write-Host '======================================'
        Write-Host '1. 首次配置 / 修复飞书工作台'
        Write-Host '2. 开始每日扫描'
        Write-Host '3. 查看健康检查'
        Write-Host '4. 打开飞书工作台'
        Write-Host '5. 退出'
        $choice = Read-Host '请输入选项 [1-5]'
        switch ($choice) {
            '1' { Invoke-Radar @('init') | Out-Null; Pause-For-User }
            '2' { Invoke-Radar @('daily') | Out-Null; Pause-For-User }
            '3' { Invoke-Radar @('check') | Out-Null; Pause-For-User }
            '4' { Invoke-Radar @('open-workspace') | Out-Null; Pause-For-User }
            '5' { exit 0 }
            default { Write-Host '请输入 1 到 5 之间的数字。'; Pause-For-User }
        }
    }
}
catch {
    Write-Host "启动失败：$($_.Exception.Message)"
    Pause-For-User
    exit 1
}
