@echo off
title MatchTrader API control
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" scripts\control.py
if errorlevel 1 pause
