@echo off
cd /d "%~dp0"
title GRDZ_SNIPE Cloud Deployer
python deploy_gui.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Blad uruchomienia kreatora Python.
    pause
)
