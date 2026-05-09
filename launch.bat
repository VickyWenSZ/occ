@echo off
cd /d "%~dp0"

:: Kill any process currently on port 7891
for /f "tokens=5" %%a in ('netstat -ano 2^>nul ^| findstr ":7891 "') do (
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
