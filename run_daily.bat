@echo off
setlocal
cd /d "%~dp0"
call "%~dp0start.bat" --config "%~dp0config.yaml" --db "%~dp0data\jobs.sqlite" daily
exit /b %ERRORLEVEL%
