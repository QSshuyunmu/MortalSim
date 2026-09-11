# 快速重启：仅精确重启本项目 bot.py（由守护进程接管），不误杀其它 python 服务
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = "C:\Users\HP\AppData\Local\Programs\Python\Python313\python.exe"
$env:NO_PROXY = "127.0.0.1,localhost"
$env:no_proxy = "127.0.0.1,localhost"
$sw = [System.Diagnostics.Stopwatch]::StartNew()

# PowerShell 5.1 的 Get-Process 无 CommandLine 属性，必须用 Get-CimInstance
$botProcs = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like "*MortalSim-Bot*bot.py*" }
foreach ($p in $botProcs) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }

$daemonAlive = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like "*MortalSim-Bot*daemon.py*" }

if (-not $daemonAlive) {
  Start-Process -FilePath $python -ArgumentList "src\daemon.py" -WorkingDirectory $root -WindowStyle Hidden
  Start-Sleep -Seconds 2
}

# 守护进程会在 5 秒内拉起 bot.py，此处等待其就绪
$deadline = (Get-Date).AddSeconds(25)
$ready = $false
while ((Get-Date) -lt $deadline) {
  $bot = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like "*MortalSim-Bot*bot.py*" }
  if ($bot) { $ready = $true; break }
  Start-Sleep -Milliseconds 500
}
$sw.Stop()
if ($ready) { "OK bot.py restarted via guardian in {0:N1}s" -f $sw.Elapsed.TotalSeconds }
else { "WARN bot.py not observed within timeout; check logs\daemon.log" }
