@echo off
rem Start OCR + MortalSim + Bot. NapCat must be started separately (admin).
echo [1/3] Starting riichi-vision OCR on port 8000...
start "OCR" /D E:\riichi-vision E:\riichi-vision\.venv\Scripts\python.exe -m uvicorn riichi_vision.app:app --app-dir backend --host 127.0.0.1 --port 8000

echo [2/3] Starting MortalSim on port 50715...
call "%~dp0start_mortalsim.cmd"

echo [3/3] Starting Bot...
call "%~dp0restart_bot_fast.cmd"

echo.
echo ============================================================
echo  OCR / MortalSim / Bot started.
echo  Now start NapCat manually:
echo    1) Close QQ if it is already running.
echo    2) Run as administrator: D:\tenhoulib\MortalSim-Bot\napcat_shell\launcher.bat
echo    3) Log in QQ bot account 3983079058 if asked.
echo ============================================================
pause
