@echo off
cd /d "%~dp0"

:: First-launch / post-update migration: if the venv doesn't exist yet, run
:: start.bat to create it (one-time). Existing users updated from the pre-venv
:: setup land here once and migrate transparently.
if not exist ".venv\Scripts\python.exe" (
    echo  First-time virtual environment setup needed. Running start.bat...
    call start.bat
    exit /b 0
)

:: Kill only the process LISTENING on port 7891 (not browser connections to it)
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":7891 " ^| findstr "LISTENING"') do (
    taskkill /F /PID %%a >nul 2>&1
)
timeout /t 1 /nobreak >nul

:: Start Ollama if not running
ollama list >nul 2>&1
if %errorlevel% neq 0 (
    start /B ollama serve
    timeout /t 3 /nobreak >nul
)

:: Start OCC Node (use venv Python)
start /B .venv\Scripts\python.exe node/apps/gui/server.py
timeout /t 2 /nobreak >nul
start http://localhost:7891
