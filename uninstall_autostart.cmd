@echo off
rem 卸载开机/登录自动拉起任务
net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
  powershell -NoProfile -Command "Start-Process '%~f0' -Verb runAs"
  exit /b
)
schtasks /Delete /TN "MortalSimBotAutoStart" /F
echo.
echo ============================================================
echo  已成功移除开机自启动任务 MortalSimBotAutoStart
echo ============================================================
pause
