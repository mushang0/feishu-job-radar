@echo off
setlocal
chcp 65001 >nul
set "PYTHONUTF8=1"
set "JOB_MONITOR_WATCH_PARENT=1"
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

if not "%~1"=="" goto :run_command

:menu
cls
echo ======================================
echo        飞书求职雷达
echo ======================================
echo  1. 首次配置 / 修复飞书工作台
echo  2. 开始每日扫描
echo  3. 查看健康检查
echo  4. 打开飞书工作台
echo  5. 退出
echo.
set /p CHOICE=请输入选项 [1-5]：
if "%CHOICE%"=="1" "%PYTHON_EXE%" -m job_monitor --config "%~dp0config.yaml" --db "%~dp0data\jobs.sqlite" init
if "%CHOICE%"=="2" "%PYTHON_EXE%" -m job_monitor --config "%~dp0config.yaml" --db "%~dp0data\jobs.sqlite" daily
if "%CHOICE%"=="3" "%PYTHON_EXE%" -m job_monitor --config "%~dp0config.yaml" --db "%~dp0data\jobs.sqlite" check
if "%CHOICE%"=="4" "%PYTHON_EXE%" -m job_monitor --config "%~dp0config.yaml" open-workspace
if "%CHOICE%"=="5" exit /b 0
echo.
if not "%CHOICE%"=="1" if not "%CHOICE%"=="2" if not "%CHOICE%"=="3" if not "%CHOICE%"=="4" echo 请输入 1 到 5 之间的数字。
echo.
pause
goto :menu

:run_command
"%PYTHON_EXE%" -m job_monitor %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
pause
exit /b %EXIT_CODE%

:python_error
echo 未找到可用的 Python 3.11。请先安装后重新运行 start.bat。
pause
exit /b 1

:install_error
echo 依赖安装失败。请检查网络连接后重新运行 start.bat。
pause
exit /b 1
