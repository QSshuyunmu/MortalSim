<#
  NapCat (QQNT + NapCat 注入) 启动 / 重启的唯一入口。
  ------------------------------------------------------------------
  被 start_all_services.ps1 与 daemon.py 共同调用，避免"启动 NapCat 的代码有两份、行为不一致"。

  免扫码登录（可选，强烈建议）：读取 data\napcat_login.env
      NAPCAT_QUICK_ACCOUNT=<QQ号>
      NAPCAT_QUICK_PASSWORD=<密码>            # 二选一（明文，NapCat 在内存里算 MD5）
      NAPCAT_QUICK_PASSWORD_MD5=<32位MD5>     # 二选一（避免明文落盘）
  这三个变量会随启动器传给 QQ.exe：NapCat 先尝试本地快速登录票据，
  失败后自动用密码回退登录，最后才退回二维码 —— 因此配了密码就不会再卡在扫码。
  注意：本文件把密码读进当前进程环境变量，不写入任何日志或配置文件。

  退出码 / 标准输出标记（供守护进程解析）：
      NAPCAT_ALREADY_RUNNING   5701 已在监听且已登录，未做任何变更
      NAPCAT_LOGIN_PENDING     5701 在听但未登录（正在扫码），脚本未做任何变更
      NAPCAT_READY             重启后 5701 已就绪
      NAPCAT_QR_REQUIRED <png> 未登录且票据失效，需要扫码（二维码路径）
      NAPCAT_FAILED            启动失败
#>
[CmdletBinding()]
param(
  [string]$Account = '',
  [switch]$Force,
  [switch]$Wait,
  [int]$TimeoutSec = 75
)

$ErrorActionPreference = 'Continue'
$root    = Split-Path -Parent $PSScriptRoot
$shell   = Join-Path $root 'napcat_shell'
$logs    = Join-Path $root 'logs'
$dataDir = Join-Path $root 'data'
$envFile = Join-Path $dataDir 'napcat_login.env'
$logFile = Join-Path $logs 'napcat_supervisor.log'
$launchLog = Join-Path $logs 'napcat_launch.log'
$qrFile  = Join-Path $shell 'cache\qrcode.png'
$oneBotPort = 5701
$httpPort   = 5700

New-Item -ItemType Directory -Force -Path $logs | Out-Null
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null

function Write-NapLog([string]$text) {
  $line = "[{0}] {1}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $text
  try { $line | Out-File $logFile -Append -Encoding utf8 } catch { }
  Write-Host $line
}

function Import-EnvFile([string]$path) {
  $cfg = @{}
  if (-not (Test-Path $path)) { return $cfg }
  foreach ($raw in (Get-Content $path -Encoding UTF8)) {
    $line = $raw.Trim()
    if (-not $line -or $line.StartsWith('#')) { continue }
    $i = $line.IndexOf('=')
    if ($i -lt 1) { continue }
    $k = $line.Substring(0, $i).Trim()
    $v = $line.Substring($i + 1).Trim().Trim('"').Trim("'")
    if ($k) { $cfg[$k] = $v }
  }
  return $cfg
}

function Test-OneBotPort {
  $null -ne (Get-NetTCPConnection -LocalPort $oneBotPort -State Listen -ErrorAction SilentlyContinue)
}

# OneBot 真正"可用"的判据：端口在听 + HTTP API 能拿到登录信息。
# 只看端口会误判 —— 旧进程退出时端口可能短暂仍在 LISTEN。
function Test-OneBotReady {
  # 注意：5701 是 WebSocket 服务，对它发 HTTP POST 会得到 426 Upgrade Required，
  # 所以先探 5700(HTTP)，失败再试 5701（仅当用户只开了 WS 时）。
  foreach ($p in @($httpPort, $oneBotPort)) {
    try {
      $r = Invoke-RestMethod -Uri ("http://127.0.0.1:$p/get_login_info") -Method Post -TimeoutSec 5
      if ($r.status -eq 'ok' -and $r.data -and $r.data.user_id) { return $true }
    } catch { }
  }
  return $false
}

# 等待端口真正关闭，避免"刚杀掉就启动、检查到的是旧监听"的假就绪
function Wait-PortClosed([int]$timeoutSec) {
  $deadline = (Get-Date).AddSeconds($timeoutSec)
  while ((Get-Date) -lt $deadline) {
    if (-not (Test-OneBotPort)) { return $true }
    Start-Sleep -Milliseconds 500
  }
  return $false
}

function Stop-NapCat {
  foreach ($n in @('NapCatWinBootMain', 'QQ')) {
    Get-Process $n -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
  }
  Start-Sleep -Seconds 2
  $closedWs = Wait-PortClosed 20
  Start-Sleep -Milliseconds 300
  $closedHttp = Wait-PortClosed 10
  if ($closedWs -and $closedHttp) { Write-NapLog "old listeners on ports $oneBotPort/$httpPort released" }
  else { Write-NapLog "WARNING: port $oneBotPort/$httpPort still in LISTEN after kill; continuing anyway" }
}

# ---------- 0. 已在运行则直接返回 ----------
if ((-not $Force) -and (Test-OneBotPort)) {
  if (Test-OneBotReady) {
    Write-NapLog "OneBot port $oneBotPort already listening and logged in; nothing to do"
    Write-Output 'NAPCAT_ALREADY_RUNNING'
    exit 0
  }
  # 端口在听但没登录 = 大概率正在扫码，绝不能杀掉打扰用户
  Write-NapLog "OneBot port $oneBotPort is listening but not logged in yet (QR login in progress?); NOT restarting"
  Write-Output 'NAPCAT_LOGIN_PENDING'
  exit 3
}

# ---------- 1. 读取登录配置 ----------
$cfg = Import-EnvFile $envFile
$account = $Account
if (-not $account) { $account = $env:NAPCAT_QUICK_ACCOUNT }
if (-not $account -and $cfg.ContainsKey('NAPCAT_QUICK_ACCOUNT')) { $account = $cfg['NAPCAT_QUICK_ACCOUNT'] }
if (-not $account) { $account = '3983079058' }

$hasPlain = $cfg.ContainsKey('NAPCAT_QUICK_PASSWORD') -and $cfg['NAPCAT_QUICK_PASSWORD']
$hasMd5   = $cfg.ContainsKey('NAPCAT_QUICK_PASSWORD_MD5') -and $cfg['NAPCAT_QUICK_PASSWORD_MD5']

# ---------- 2. 停止旧实例 ----------
if ($Force) {
  Write-NapLog "Force restart requested; killing existing QQ/NapCat processes"
  Stop-NapCat
}

$launcher = Join-Path $shell 'launcher-user.bat'
if (-not (Test-Path $launcher)) {
  Write-NapLog "launcher not found: $launcher"
  Write-Output 'NAPCAT_FAILED'
  exit 1
}

# ---------- 3. 注入登录环境变量并拉起 ----------
$env:NAPCAT_QUICK_ACCOUNT = $account
if ($hasPlain) {
  $env:NAPCAT_QUICK_PASSWORD = $cfg['NAPCAT_QUICK_PASSWORD']
  Remove-Item Env:NAPCAT_QUICK_PASSWORD_MD5 -ErrorAction SilentlyContinue
} elseif ($hasMd5) {
  $env:NAPCAT_QUICK_PASSWORD_MD5 = $cfg['NAPCAT_QUICK_PASSWORD_MD5']
  Remove-Item Env:NAPCAT_QUICK_PASSWORD -ErrorAction SilentlyContinue
}

if ($hasPlain -or $hasMd5) {
  Write-NapLog "launching NapCat for QQ $account (quick-login ticket + password fallback, no QR expected)"
} else {
  Write-NapLog "launching NapCat for QQ $account (quick-login ticket only; QR may be required) - 建议在 $envFile 里配置 NAPCAT_QUICK_PASSWORD 实现免扫码"
}

$cmdArgs = '/c ' + $launcher + ' -q ' + $account + ' > "' + $launchLog + '" 2>&1'
Start-Process -FilePath 'cmd.exe' -ArgumentList $cmdArgs -WorkingDirectory $shell -WindowStyle Hidden
Write-NapLog "launcher started (cwd=$shell)"

if (-not $Wait) {
  Write-Output 'NAPCAT_LAUNCHED'
  exit 0
}

# ---------- 4. 等待 OneBot 端口就绪 ----------
$deadline = (Get-Date).AddSeconds($TimeoutSec)
while ((Get-Date) -lt $deadline) {
  if (Test-OneBotReady) {
    Write-NapLog "OneBot port $oneBotPort is up and logged in; NapCat ready"
    Write-Output 'NAPCAT_READY'
    exit 0
  }
  Start-Sleep -Seconds 3
}

if (Test-Path $qrFile) {
  $age = [int]((Get-Date) - (Get-Item $qrFile).LastWriteTime).TotalSeconds
  Write-NapLog "OneBot port $oneBotPort not up and QR login is pending (qr age ${age}s): $qrFile"
  Write-Output ("NAPCAT_QR_REQUIRED " + $qrFile)
  exit 2
}

Write-NapLog "OneBot port $oneBotPort still down after ${TimeoutSec}s and no QR file"
Write-Output 'NAPCAT_FAILED'
exit 1
