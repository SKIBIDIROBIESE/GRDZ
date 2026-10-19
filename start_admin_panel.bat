@echo off
title GRDZ-SNIPE // Portal Launcher
cd /d "%~dp0app"

start "" pythonw.exe admin_server.py
ping 127.0.0.1 -n 2 >nul
start http://grdzsnipe.com
exit
