@echo off
title MatchTrader paper stop-limit (account 276954, no broker writes)
cd /d "%~dp0"
if not exist "data\paper" mkdir "data\paper"
del /q "data\paper\stop-limit.stop" 2>nul
set PYTHONPATH=%~dp0src
"%~dp0.venv\Scripts\python.exe" -u -m matchtrader.orders.paper_stop_limit ^
  --ledger "C:\HCAMM\trials\R01_TRADES.csv" --env ".env" --account 276954 ^
  --symbol BTCUSD --destination BTCUSD --risk 5 --tolerance 5 ^
  --db "data\paper\stop-limit-paper.sqlite3" --stop-file "data\paper\stop-limit.stop" ^
  >> "data\paper\stop-limit-paper.log" 2>&1
if errorlevel 1 pause
