@echo off
rem Start MortalSim on fixed port 50715 for the QQ bot (skip if already running).
netstat -ano | findstr ":50715" | findstr "LISTENING" >nul 2>&1
if %ERRORLEVEL%==0 (
  echo MortalSim is already listening on 50715.
  exit /b 0
)
set "NO_PROXY=127.0.0.1,localhost"
set "no_proxy=127.0.0.1,localhost"
set "MORTALSIM_DATA_DIR=D:\tenhoulib\MortalSim-Local-v0.3.0-rc.1-new10\data"
set "MORTALSIM_ENGINE=lite"
set "MORTALSIM_PORT=50715"
set "MORTALSIM_NO_BROWSER=1"
start "" "D:\tenhoulib\MortalSim-Local-v0.3.0-rc.1-new10\MortalSim.exe"
