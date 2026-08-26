# MortalSim-Bot 全套服务一键启动编排脚本（精简版，不含 OCR）
$ErrorActionPreference = "Continue"
$root = "D:\tenhoulib\MortalSim-Bot"
$logs = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$logFile = Join-Path $logs "system_startup.log"
"=== MortalSim-Bot 全套服务启动 [$stamp] ===" | Out-File $logFile -Encoding utf8

$env:NO_PROXY = "127.0.0.1,localhost"
$env:no_proxy = "127.0.0.1,localhost"

# 1. 检查并启动 MortalSim 本地后端 (50715 端口)
$msListening = Get-NetTCPConnection -LocalPort 50715 -State Listen -ErrorAction SilentlyContinue
if ($null -eq $msListening) {
    Write-Host "[1/3] 启动 MortalSim 后端 (端口 50715)..." -ForegroundColor Cyan
    $msRoot = "D:\tenhoulib\MortalSim-Local-v0.3.0-rc.1-new10"
    $msExe = Join-Path $msRoot "MortalSim.exe"
    $env:MORTALSIM_DATA_DIR = Join-Path $msRoot "data"
    $env:MORTALSIM_ENGINE = "lite"
    $env:MORTALSIM_PORT = "50715"
    $env:MORTALSIM_NO_BROWSER = "1"
    Start-Process -FilePath $msExe -WorkingDirectory $msRoot -WindowStyle Hidden
    "MortalSim backend started." | Out-File $logFile -Append -Encoding utf8
} else {
    Write-Host "[1/3] MortalSim 后端已在运行 (端口 50715)" -ForegroundColor Green
}

# 2. 检查并启动 NapCat OneBot 桥接器与 QQ 快捷登录
$napListening = Get-NetTCPConnection -LocalPort 5701 -State Listen -ErrorAction SilentlyContinue
if ($null -eq $napListening) {
    Write-Host "[2/3] 启动 NapCat QQ 快捷登录 (3983079058)..." -ForegroundColor Cyan
    Get-Process QQ,NapCatWinBootMain -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 800

    $napShell = Join-Path $root "napcat_shell"
    $launcher = Join-Path $napShell "launcher-user.bat"
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c","`"cd /d `"$napShell`" && `"$launcher`" -q 3983079058`"" -WindowStyle Hidden
    "NapCat QQ launcher triggered." | Out-File $logFile -Append -Encoding utf8
} else {
    Write-Host "[2/3] NapCat OneBot 服务已在运行 (端口 5701)" -ForegroundColor Green
}

# 3. 启动 Bot 进程（确保单实例）
Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -like '*Python313*' -or ($_.Path -notlike '*riichi-vision*' -and $_.Path -notlike '*cpython-3.12*' -and $_.Path -notlike '*lingtai*')
} | ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }
Remove-Item (Join-Path $root "data\bot.lock") -Force -ErrorAction SilentlyContinue
Write-Host "[3/3] 启动 MortalSim-Bot 消息处理主程序..." -ForegroundColor Cyan
$pythonExe = "C:\Users\HP\AppData\Local\Programs\Python\Python313\python.exe"
Start-Process -FilePath $pythonExe `
  -ArgumentList "src\bot.py" -WorkingDirectory $root -WindowStyle Hidden `
  -RedirectStandardOutput (Join-Path $logs "bot.log") -RedirectStandardError (Join-Path $logs "bot.err")
"Bot process launched." | Out-File $logFile -Append -Encoding utf8

Write-Host ""
Write-Host "============================================================" -ForegroundColor Yellow
Write-Host " 全套服务拉起完成！" -ForegroundColor Green
Write-Host "   - MortalSim API: http://127.0.0.1:50715"
Write-Host "   - NapCat WebUI:  http://127.0.0.1:6099"
Write-Host "   - QQ Bot WS:     ws://127.0.0.1:5701"
Write-Host "============================================================" -ForegroundColor Yellow
Write-Host ""