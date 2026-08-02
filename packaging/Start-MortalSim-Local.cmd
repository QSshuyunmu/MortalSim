@echo off
setlocal
set "MORTALSIM_DATA_DIR=%~dp0data"
set "MORTALSIM_ENGINE=lite"
start "" "%~dp0MortalSim.exe"
