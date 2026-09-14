@echo off
title MatchTrader API
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" scripts\control.py --setup --detach --auto-start
if errorlevel 1 pause
