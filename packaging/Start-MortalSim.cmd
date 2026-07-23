@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-MortalSim.ps1"
if errorlevel 1 (
  echo.
  echo MortalSim could not start. Read the error above, then press any key to close.
  pause >nul
)
