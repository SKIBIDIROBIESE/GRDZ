@echo off
title GRDZ-SNIPE // Portal Launcher
cd /d "%~dp0"

set PYTHONW=pythonw.exe
if exist "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" (
    set PYTHONW=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe
)

start "" "%PYTHONW%" admin_server.py
ping 127.0.0.1 -n 2 >nul
start http://grdzsnipe.com
exit
