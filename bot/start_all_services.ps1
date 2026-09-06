# MortalSim-Bot 全套服务一键启动编排脚本（更新为最新原生 Python 引擎架构）
$ErrorActionPreference = "Continue"
$root = "D:\tenhoulib\MortalSim-Bot"
$logs = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$logFile = Join-Path $logs "system_startup.log"
"=== MortalSim-Bot 全套服务启动 [$stamp] ===" | Out-File $logFile -Encoding utf8

$env:NO_PROXY = "127.0.0.1,localhost"
$env:no_proxy = "127.0.0.1,localhost"
$pythonExe = "C:\Users\HP\AppData\Local\Programs\Python\Python313\python.exe"

# 1. 检查并启动 MortalSim 最新后端 (50715 端口)
$msListening = Get-NetTCPConnection -LocalPort 50715 -State Listen -ErrorAction SilentlyContinue
if ($null -eq $msListening) {
    Write-Host "[1/3] 启动 MortalSim 新版后端服务 (端口 50715)..." -ForegroundColor Cyan
    $mortalDir = "D:\tenhoulib\MortalSim"
    $env:MORTALSIM_DATA_DIR = "D:\tenhoulib\MortalSim-Local-v0.3.0-rc.1-new10\data"
    $env:MORTALSIM_PORT = "50715"
    $env:MORTALSIM_NO_BROWSER = "1"

    Start-Process -FilePath $pythonExe -ArgumentList "run_mortalsim.py" -WorkingDirectory $mortalDir -WindowStyle Hidden
    Start-Sleep -Seconds 3
    "MortalSim native backend started." | Out-File $logFile -Append -Encoding utf8
} else {
    Write-Host "[1/3] MortalSim 后端已在运行 (端口 50715)" -ForegroundColor Green
}

# 2. 检查并启动 NapCat OneBot 桥接器与 QQ 快捷登录 (端口 5701 / 5700)
$napListening = Get-NetTCPConnection -LocalPort 5701 -State Listen -ErrorAction SilentlyContinue
if ($null -eq $napListening) {
    Write-Host "[2/3] 启动 NapCat QQ 快捷登录 (3983079058)..." -ForegroundColor Cyan
    Get-Process QQ,NapCatWinBootMain -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 800

    $napShell = Join-Path $root "napcat_shell"
    $launcher = Join-Path $napShell "launcher-user.bat"
    Start-Process -FilePath "cmd.exe" -ArgumentList "/c","`"cd /d `"$napShell`" && `"$launcher`" -q 3983079058`"" -WindowStyle Hidden
    Start-Sleep -Seconds 6
    "NapCat QQ launcher triggered." | Out-File $logFile -Append -Encoding utf8
} else {
    Write-Host "[2/3] NapCat OneBot 服务已在运行 (端口 5701)" -ForegroundColor Green
}

# 3. 启动守护进程 Daemon（由 Daemon 统一管控并拉起单例 bot.py）
Write-Host "[3/3] 启动 MortalSim-Bot 守护进程与消息主程序..." -ForegroundColor Cyan

Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -like '*bot.py*' -or $_.CommandLine -like '*daemon.py*'
} | ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }

Remove-Item (Join-Path $root "data\bot.lock") -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $root "data\*.lock") -Force -ErrorAction SilentlyContinue

# 仅由 Daemon 负责拉起 bot.py，杜绝同时拉起产生的竞争！
Start-Process -FilePath $pythonExe -ArgumentList "src\daemon.py" -WorkingDirectory $root -WindowStyle Hidden
"Daemon process launched (daemon will manage bot.py)." | Out-File $logFile -Append -Encoding utf8

Write-Host ""
Write-Host "============================================================" -ForegroundColor Yellow
Write-Host " 全套服务拉起完成！" -ForegroundColor Green
Write-Host "   - MortalSim API: http://127.0.0.1:50715"
Write-Host "   - NapCat HTTP:   http://127.0.0.1:5700"
Write-Host "   - QQ Bot WS:     ws://127.0.0.1:5701"
Write-Host "============================================================" -ForegroundColor Yellow
Write-Host ""
