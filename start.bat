@echo off
setlocal

REM T-Drive Windows Startup Script
REM Starts the PowerShell launcher, which handles readiness checks and browser opening.

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

powershell -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start.ps1"
