@echo off
cd /d "%~dp0"

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

:: Start OCC Node
start /B python node/apps/gui/server.py
timeout /t 2 /nobreak >nul
start http://localhost:7891
