# Fast restart: kill + start, return immediately (no connection wait)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = "C:\Users\HP\AppData\Local\Programs\Python\Python313\python.exe"
$log = Join-Path $root "logs\bot.log"
$err = Join-Path $root "logs\bot.err"
$env:NO_PROXY="127.0.0.1,localhost"
$env:no_proxy="127.0.0.1,localhost"
$sw = [System.Diagnostics.Stopwatch]::StartNew()

Get-Process python -ErrorAction SilentlyContinue | Where-Object {
    $_.Path -like '*Python313*' -or ($_.Path -notlike '*riichi-vision*' -and $_.Path -notlike '*cpython-3.12*' -and $_.Path -notlike '*lingtai*')
} | ForEach-Object { Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue }

Remove-Item $log,$err -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $root "data\bot.lock") -Force -ErrorAction SilentlyContinue

$p = Start-Process -FilePath $python -ArgumentList 'src\bot.py' -WorkingDirectory $root `
  -RedirectStandardOutput $log -RedirectStandardError $err -PassThru -WindowStyle Hidden
$sw.Stop()
Write-Output ("OK started PID={0} in {1:N1}s (connection happens in background)" -f $p.Id, $sw.Elapsed.TotalSeconds)