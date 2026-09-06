# Fast restart: 停止旧 Bot 进程，清理锁文件，拉起最新 Bot 进程
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = "C:\Users\HP\AppData\Local\Programs\Python\Python313\python.exe"
$log = Join-Path $root "logs\bot.log"
$err = Join-Path $root "logs\bot.err"
$env:NO_PROXY="127.0.0.1,localhost"
$env:no_proxy="127.0.0.1,localhost"
$sw = [System.Diagnostics.Stopwatch]::StartNew()

Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    $_.CommandLine -like '*bot.py*'
} | ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }

Remove-Item $log,$err -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $root "data\bot.lock") -Force -ErrorAction SilentlyContinue

$p = Start-Process -FilePath $python -ArgumentList '-u','src\bot.py' -WorkingDirectory $root `
  -RedirectStandardOutput $log -RedirectStandardError $err -PassThru -WindowStyle Hidden
$sw.Stop()
Write-Output ("OK started PID={0} in {1:N1}s (connection happens in background)" -f $p.Id, $sw.Elapsed.TotalSeconds)
