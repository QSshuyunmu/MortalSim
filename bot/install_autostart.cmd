@echo off
rem 注册/修复 开机与登录 自启动计划任务（需管理员，脚本会自动提权）
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0register_autostart.ps1"
pause
