<#
  MortalSim-Bot 全套服务一键启动 / 自愈编排脚本
  ------------------------------------------------------------------
  关键修复（历史缺陷）：PowerShell 5.1 的 Get-Process 对象没有 CommandLine 属性，
  旧脚本用 `Get-Process python | Where-Object { $_.CommandLine -like '*bot.py*' }`
  杀旧进程永远匹配 0 个 → 旧守护进程继续持有 Win32 互斥体 → 新守护进程启动即退出，
  表现为"重启成功但服务没起来"。本脚本一律改用 Get-CimInstance Win32_Process。
#>
[CmdletBinding()]
param(
  [switch]$SkipNapCat,
  [switch]$Quiet
)

$ErrorActionPreference = "Continue"
$root = "D:\tenhoulib\MortalSim-Bot"
$logs = Join-Path $root "logs"
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$logFile = Join-Path $logs "system_startup.log"
$stamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

function Write-StartupLog([string]$text) {
  "[$stamp] $text" | Out-File $logFile -Append -Encoding utf8
  if (-not $Quiet) { Write-Host $text }
}

$env:NO_PROXY = "127.0.0.1,localhost"
$env:no_proxy = "127.0.0.1,localhost"
$pythonExe = "C:\Users\HP\AppData\Local\Programs\Python\Python313\python.exe"

function Get-ProjectProcesses {
  param([string]$Pattern)
  Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -like "*$Pattern*" -and $_.CommandLine -notlike "*Get-CimInstance*" }
}

function Test-Port([int]$Port) {
  $null -ne (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
}

Write-StartupLog "=== MortalSim-Bot 全套服务启动 ==="

# ---------- 0. 停止旧实例（精确按 cmdline 匹配，绝不误杀其它 python 服务）----------
$staleDaemon = Get-ProjectProcesses "*MortalSim-Bot*daemon.py*"
$staleBot    = Get-ProjectProcesses "*MortalSim-Bot*bot.py*"
foreach ($p in @($staleDaemon) + @($staleBot)) {
  if ($p) {
    Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue
    Write-StartupLog "stopped stale pid=$($p.ProcessId)"
  }
}
# 兜底：历史上有守护进程用相对路径 "src\daemon.py" 启动，命令行里不含 "MortalSim-Bot"，
# 上面的 cmdline 过滤会漏判 -> 旧守护进程继续持有互斥体 -> 新守护进程启动即退出。
# 因此再用 PID 落盘文件（daemon.pid / bot.heartbeat）兜底清理，并校验进程确实是 daemon.py/bot.py。
$pidTargets = @()
$daemonPidFile = Join-Path $root "data\daemon.pid"
if (Test-Path $daemonPidFile) {
  $raw = Get-Content $daemonPidFile -Raw -ErrorAction SilentlyContinue
  if ($raw -match '(\d+)') { $pidTargets += ,@{ Id = [int]$Matches[1]; Tag = 'daemon' } }
}
$botHbFile = Join-Path $root "data\bot.heartbeat"
if (Test-Path $botHbFile) {
  $raw = Get-Content $botHbFile -Raw -ErrorAction SilentlyContinue
  if ($raw -match 'pid=(\d+)') { $pidTargets += ,@{ Id = [int]$Matches[1]; Tag = 'bot' } }
}
foreach ($t in $pidTargets) {
  $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$($t.Id)" -ErrorAction SilentlyContinue
  if ($proc -and $proc.Name -eq 'python.exe' -and $proc.CommandLine -match 'daemon\.py|bot\.py') {
    Stop-Process -Id $t.Id -Force -ErrorAction SilentlyContinue
    Write-StartupLog "stopped $($t.Tag) from pid-file pid=$($t.Id)"
    Start-Sleep -Milliseconds 900
  }
}

Get-ChildItem (Join-Path $root "data\*.lock") -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue

# ---------- 1. MortalSim 仿真后端 (50715) ----------
if (-not (Test-Port 50715)) {
  $mortalDir = "D:\tenhoulib\MortalSim"
  $env:MORTALSIM_DATA_DIR = "D:\tenhoulib\MortalSim-Local-v0.3.0-rc.1-new10\data"
  $env:MORTALSIM_PORT = "50715"
  $env:MORTALSIM_NO_BROWSER = "1"
  Start-Process -FilePath $pythonExe -ArgumentList "run_mortalsim.py" -WorkingDirectory $mortalDir -WindowStyle Hidden
  Write-StartupLog "MortalSim backend launch requested (port 50715)"
  Start-Sleep -Seconds 3
} else {
  Write-StartupLog "MortalSim backend already listening on 50715"
}

# ---------- 2. NapCat OneBot (5700/5701) ----------
# 统一走 scripts\start_napcat.ps1（唯一入口，daemon.py 掉线时也调它），
# 由它负责注入免扫码登录环境变量、杀旧实例、等待端口就绪、必要时报告需要扫码。
if (-not $SkipNapCat) {
  $napHelper = Join-Path $root "scripts\start_napcat.ps1"
  if (Test-Path $napHelper) {
    if (Test-Port 5701) {
      Write-StartupLog "NapCat OneBot already listening on 5701"
    } else {
      Write-StartupLog "NapCat OneBot (5701) is down; invoking scripts\start_napcat.ps1 -Wait"
      $napOut = & $napHelper -Wait -TimeoutSec 75 2>&1
      foreach ($line in @($napOut)) { Write-StartupLog ("napcat> " + $line) }
    }
  } else {
    Write-StartupLog "NapCat helper script not found: $napHelper"
  }
}

# ---------- 3. 守护进程（由它统一监督 bot.py 与后端）----------
# 必须以绝对路径启动：相对路径 "src\daemon.py" 会让命令行里不含 "MortalSim-Bot"，
# 从而被所有基于 command line 的进程过滤器漏判（历史缺陷之一）。
$existingDaemon = Get-ProjectProcesses "*MortalSim-Bot*daemon.py*" | Select-Object -First 1
if ($existingDaemon) {
  Write-StartupLog "daemon already running pid=$($existingDaemon.ProcessId)"
} else {
  Start-Process -FilePath $pythonExe -ArgumentList (Join-Path $root "src\daemon.py") -WorkingDirectory $root -WindowStyle Hidden
  Write-StartupLog "daemon launched (guardian manages bot.py + backend)"
}

# 后端为 PyTorch/CUDA 冷启动，最长等待 40 秒确认端口就绪
$backendDeadline = (Get-Date).AddSeconds(40)
while ((Get-Date) -lt $backendDeadline -and -not (Test-Port 50715)) { Start-Sleep -Seconds 2 }

$daemonPid = (Get-ProjectProcesses "*MortalSim-Bot*daemon.py*" | Select-Object -First 1).ProcessId
$botProc   = Get-ProjectProcesses "*MortalSim-Bot*bot.py*" | Select-Object -First 1
$ports = foreach ($p in 50715, 5700, 5701) {
  if (Test-Port $p) { "$p=UP" }
  elseif ($p -eq 50715) { "50715=DOWN(backend cold-starting)" }
  else { "$p=WAIT_LOGIN(需扫码登录 NapCat)" }
}
Write-StartupLog "daemon_pid=$daemonPid bot_pid=$($botProc.ProcessId) ports: $($ports -join ' ')"
"READY daemon=$daemonPid bot=$($botProc.ProcessId) ports=$($ports -join ',')"
