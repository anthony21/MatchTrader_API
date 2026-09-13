@echo off
cd /d "%~dp0"
if not exist "data\paper" mkdir "data\paper"
type nul > "data\paper\stop-limit.stop"
echo Stop requested. The paper runner closes within a few seconds; its record stays in data\paper.
