@echo off
setlocal
:: Change directory to the project folder
cd /d "%~dp0"

set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" (
    echo 找不到项目虚拟环境：%PYTHON_EXE%
    echo 请先运行：python -m venv .venv ^&^& .\.venv\Scripts\Activate.ps1 ^&^& python -m pip install -e .
    exit /b 1
)

:: Run the daily sync job with deterministic project-local paths
"%PYTHON_EXE%" -m job_monitor --config "%~dp0config.yaml" --db "%~dp0data\jobs.sqlite" daily
exit /b %ERRORLEVEL%
