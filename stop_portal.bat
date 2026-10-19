@echo off
title GRDZ-SNIPE // Zatrzymywanie Portalu
cd /d "%~dp0"

echo ====================================================================
echo   GRDZ-SNIPE - ZATRZYMYWANIE SERWERA PORTALU W TLE
echo ====================================================================
echo.

powershell -NoProfile -Command "Get-Process -Name python, pythonw -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like '*admin_server.py*' } | Stop-Process -Force"

echo [OK] Procesy serwera portalu zostaly zatrzymane.
timeout /t 2 /nobreak >nul
