@echo off
rem MortalSim-Bot scheduled task / auto startup entry point
net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
  powershell -NoProfile -Command "Start-Process '%~f0' -Verb runAs"
  exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_all_services.ps1"
