@echo off
title KhataSnap — Stopping All Services
color 0C

echo ================================================================
echo       KhataSnap — Stopping All Services
echo ================================================================
echo.

echo Stopping Python services (uvicorn)...
taskkill /F /FI "WINDOWTITLE eq KhataSnap Orchestrator*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq KhataSnap OCR*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq KhataSnap SRE*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq KhataSnap Inventory*" >nul 2>&1

echo Stopping Node services...
taskkill /F /FI "WINDOWTITLE eq KhataSnap Voice*" >nul 2>&1
taskkill /F /FI "WINDOWTITLE eq KhataSnap Frontend*" >nul 2>&1

echo.
echo All services stopped.
echo.
pause
