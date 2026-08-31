@echo off
setlocal
rem MortalSim 新版服务直接启动脚本
set "NO_PROXY=127.0.0.1,localhost"
set "no_proxy=127.0.0.1,localhost"
set "MORTALSIM_DATA_DIR=D:\tenhoulib\MortalSim-Local-v0.3.0-rc.1-new10\data"
set "MORTALSIM_PORT=50715"
set "MORTALSIM_NO_BROWSER=1"

set "PYTHON=C:\Users\HP\AppData\Local\Programs\Python\Python313\python.exe"
if exist "%PYTHON%" (
  start "MortalSim" /B "%PYTHON%" "%~dp0run_mortalsim.py"
  exit /b 0
)
start "MortalSim" /B py -3.13 "%~dp0run_mortalsim.py"
endlocal
