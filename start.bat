@echo off
chcp 65001 >nul
title OCC Node

echo.
echo  OCC Node
echo  ════════════════════════════
echo.

:: ── 1. Python ────────────────────────────────────────────────────────────────
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo  [!] Python not found.
    echo      Download Python 3.11+ from: https://www.python.org/downloads
    echo      During installation, check "Add Python to PATH".
    echo.
    start https://www.python.org/downloads
    pause
    exit /b 1
)
echo  [OK] Python found.

:: ── 2. Ollama ─────────────────────────────────────────────────────────────────
where ollama >nul 2>&1
if %errorlevel% neq 0 (
    echo  [!] Ollama not found.
    echo      Download Ollama from: https://ollama.com/download
    echo      After installing, run this script again.
    echo.
    start https://ollama.com/download
    pause
    exit /b 1
)
echo  [OK] Ollama found.

:: ── 3. Python dependencies ───────────────────────────────────────────────────
echo  Installing dependencies ^(skipped if already up to date^)...
python -m pip install -r node/requirements.txt -q
if %errorlevel% neq 0 (
    echo  [!] Failed to install dependencies. Check your internet connection.
    pause
    exit /b 1
)
echo  [OK] Dependencies ready.

:: ── 4. Detect model ──────────────────────────────────────────────────────────
echo  Detecting hardware...
python -c "from node.hardware import get_profile; print(get_profile()['model'])" > "%TEMP%\occ_model.txt" 2>nul
if %errorlevel% neq 0 (
    echo  [!] Could not detect hardware profile.
    pause
    exit /b 1
)
set /p OCC_MODEL=<"%TEMP%\occ_model.txt"
del "%TEMP%\occ_model.txt" >nul 2>&1
echo  [OK] Model: %OCC_MODEL%

:: ── 5. Start Ollama (needed for pull) ────────────────────────────────────────
echo  Starting Ollama...
ollama list >nul 2>&1
if %errorlevel% neq 0 (
    start /B ollama serve
    timeout /t 4 /nobreak >nul
)
echo  [OK] Ollama running.

:: ── 6. Pull model if needed ──────────────────────────────────────────────────
ollama show %OCC_MODEL% >nul 2>&1
if %errorlevel% neq 0 (
    echo  Downloading model %OCC_MODEL%...
    echo  This may take several minutes. Do not close this window.
    echo.
    ollama pull %OCC_MODEL%
    if %errorlevel% neq 0 (
        echo  [!] Model download failed. Check your internet connection and try again.
        pause
        exit /b 1
    )
    echo  [OK] Model downloaded.

    :: ── 7. Restart Ollama so it registers the new model ─────────────────────
    echo  Restarting Ollama...
    taskkill /F /IM ollama.exe >nul 2>&1
    timeout /t 2 /nobreak >nul
    start /B ollama serve
    timeout /t 4 /nobreak >nul
    echo  [OK] Ollama restarted.
) else (
    echo  [OK] Model already installed.
)

:: ── 8. Generate icons ────────────────────────────────────────────────────────
echo  Generating icons...
python make_icons.py
if %errorlevel% neq 0 (
    echo  [!] Icon generation failed ^(non-critical, continuing^).
)

:: ── 9. Create desktop shortcut ───────────────────────────────────────────────
echo  Creating desktop shortcut...
python setup_shortcut.py
if %errorlevel% neq 0 (
    echo  [!] Shortcut creation failed ^(non-critical, continuing^).
)

:: ── 10. Start GUI ─────────────────────────────────────────────────────────────
echo.
echo  Starting OCC Node...
echo  Opening browser at http://localhost:7891
echo.
python node/apps/gui/server.py
