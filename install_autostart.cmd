@echo off
rem 注册开机/登录自动静默拉起全套服务（需以管理员身份运行一次）
net session >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
  powershell -NoProfile -Command "Start-Process '%~f0' -Verb runAs"
  exit /b
)
schtasks /Create /TN "MortalSimBotAutoStart" /TR "powershell.exe -NoProfile -ExecutionPolicy Bypass -File D:\tenhoulib\MortalSim-Bot\start_all_services.ps1" /SC ONLOGON /RL HIGHEST /F
echo.
echo ============================================================
echo  开机自启动计划任务已成功安装: MortalSimBotAutoStart
echo  以后每次开机登录 Windows，系统将以最高权限静默拉起全套服务。
echo ============================================================
pause
