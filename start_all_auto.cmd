@echo off
rem MortalSim-Bot scheduled-task entry point (task already runs with highest privileges)
powershell -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File "%~dp0start_all_services.ps1"
