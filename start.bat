@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "JOB_MONITOR_WATCH_PARENT=1"
set "_PARENT_PID_FILE=%TEMP%\feishu-job-radar-parent-%RANDOM%.txt"
powershell.exe -NoProfile -Command "[Console]::Write((Get-CimInstance Win32_Process -Filter ('ProcessId=' + $PID)).ParentProcessId)" > "%_PARENT_PID_FILE%"
set /p JOB_MONITOR_PARENT_PID=<"%_PARENT_PID_FILE%"
del "%_PARENT_PID_FILE%" >nul 2>&1
cd /d "%~dp0"

set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    echo 正在准备 Python 3.11 虚拟环境，请稍候...
    py.exe -3.11 -m venv "%~dp0.venv"
    if errorlevel 1 goto :python_error
)

"%PYTHON_EXE%" -c "import job_monitor" >nul 2>&1
if errorlevel 1 (
    echo 正在安装项目依赖，请稍候...
    "%PYTHON_EXE%" -m pip install -e .
    if errorlevel 1 goto :install_error
)

if "%~1"=="" (
    "%PYTHON_EXE%" -m job_monitor init
) else (
    "%PYTHON_EXE%" -m job_monitor %*
)
exit /b %ERRORLEVEL%

:python_error
echo 未找到可用的 Python 3.11。请先安装 Python 3.11 后重新运行 start.bat。
exit /b 1

:install_error
echo 依赖安装失败。请检查网络连接后重新运行 start.bat。
exit /b 1
