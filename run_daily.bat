@echo off
:: Change directory to the project folder
cd /d "%~dp0"

:: Set python path to find the src folder
set PYTHONPATH=src

:: Run the daily sync job
python -m job_monitor daily
