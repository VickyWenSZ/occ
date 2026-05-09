@echo off
cd /d "%~dp0"

:: If server already on 7891, just open browser
netstat -an 2>nul | findstr ":7891 " >nul 2>&1
if %errorlevel% equ 0 (
    start http://localhost:7891
    exit /b 0
)

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
