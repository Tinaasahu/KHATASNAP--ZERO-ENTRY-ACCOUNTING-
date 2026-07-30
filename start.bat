@echo off
title KhataSnap — Starting All Services
color 0A

echo ================================================================
echo       KhataSnap — Unified Startup Script (Windows)
echo ================================================================
echo.

set ROOT=%~dp0
set BACKEND=%ROOT%Khatasnap
set FRONTEND=%ROOT%Khatasnap\frontend

:: ── Step 1: Install Python dependencies ──────────────────────────────
echo [1/6] Checking Python dependencies...
cd /d "%BACKEND%"
pip install fastapi uvicorn python-dotenv httpx flask flask-cors >nul 2>&1
echo       Done.
echo.

:: ── Step 2: Run database migration ──────────────────────────────────
echo [2/6] Running database migration...
python migrate.py
echo.

:: ── Step 3: Start OCR Service (port 8001) ────────────────────────────
echo [3/6] Starting OCR Service on port 8001...
start "KhataSnap OCR (8001)" /MIN cmd /c "cd /d "%BACKEND%" && python services\ocr_service.py"
ping 127.0.0.1 -n 3 > nul

:: ── Step 4: Start Voice Service (port 8002) ──────────────────────────
echo [4/6] Starting Voice Service on port 8002...
cd /d "%BACKEND%\services"
if not exist node_modules (
    echo       Installing Node dependencies...
    npm init -y >nul 2>&1
    npm install express cors >nul 2>&1
)
start "KhataSnap Voice (8002)" /MIN cmd /c "cd /d "%BACKEND%\services" && set VOICE_SERVICE_PORT=8002 && node voice_service.js"
cd /d "%BACKEND%"
ping 127.0.0.1 -n 3 > nul

:: ── Step 5: Start SRE Service (port 8003) ────────────────────────────
echo [5/6] Starting SRE Service on port 8003...
start "KhataSnap SRE (8003)" /MIN cmd /c "cd /d "%BACKEND%" && python services\sre_service.py"
ping 127.0.0.1 -n 5 > nul

:: ── Step 5b: Start Inventory Service (port 8004) ─────────────────────
echo       Starting Inventory Service on port 8004...
start "KhataSnap Inventory (8004)" /MIN cmd /c "cd /d "%BACKEND%" && python services\inventory_service.py"
ping 127.0.0.1 -n 2 > nul

:: ── Step 6: Start Orchestrator (port 8000) ───────────────────────────
echo [6/6] Starting Orchestrator on port 8000...
start "KhataSnap Orchestrator (8000)" /MIN cmd /c "cd /d "%BACKEND%" && python orchestrator_api.py"
ping 127.0.0.1 -n 4 > nul

:: ── Step 7: Start Frontend (port 3000) ───────────────────────────────
echo.
echo Starting Frontend on port 3000...
cd /d "%FRONTEND%"
if not exist node_modules (
    echo       Installing frontend dependencies...
    call npm install
)
start "KhataSnap Frontend (3000)" /MIN cmd /c "cd /d "%FRONTEND%" && npm run dev -- --port 3000"

:: ── Health checks ────────────────────────────────────────────────────
echo.
echo ================================================================
echo  Waiting for services to start...
echo ================================================================
ping 127.0.0.1 -n 6 > nul

echo.
echo  Service Status:
echo  ───────────────────────────────────────────
curl -s http://127.0.0.1:8000/health >nul 2>&1 && (echo   [OK] Orchestrator   - port 8000) || (echo   [!!] Orchestrator   - port 8000 NOT READY)
curl -s http://127.0.0.1:8001/health >nul 2>&1 && (echo   [OK] OCR Service    - port 8001) || (echo   [!!] OCR Service    - port 8001 NOT READY)
curl -s http://127.0.0.1:8002/health >nul 2>&1 && (echo   [OK] Voice Service  - port 8002) || (echo   [!!] Voice Service  - port 8002 NOT READY)
curl -s http://127.0.0.1:8003/health >nul 2>&1 && (echo   [OK] SRE Service    - port 8003) || (echo   [!!] SRE Service    - port 8003 NOT READY)
curl -s http://127.0.0.1:8004/health >nul 2>&1 && (echo   [OK] Inventory      - port 8004) || (echo   [!!] Inventory      - port 8004 NOT READY)
curl -s http://127.0.0.1:3000 >nul 2>&1 && (echo   [OK] Frontend       - port 3000) || (echo   [..] Frontend       - port 3000 starting...)
echo  ───────────────────────────────────────────
echo.
echo  Open http://localhost:3000 in your browser
echo.
echo  Press any key to keep this window open...
pause >nul
