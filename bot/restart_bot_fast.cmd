@echo off
rem MortalSim-Bot fast restart script (auto-elevates to admin)
net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
  powershell -NoProfile -Command "Start-Process '%~f0' -Verb runAs"
  exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0restart_bot_fast.ps1"
