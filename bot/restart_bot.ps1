# 完整重启：重启守护进程 + 由守护进程重新拉起 bot.py
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = "C:\Users\HP\AppData\Local\Programs\Python\Python313\python.exe"
$env:NO_PROXY = "127.0.0.1,localhost"
$env:no_proxy = "127.0.0.1,localhost"

# 精确匹配本项目进程（PowerShell 5.1 无 Get-Process CommandLine）
$targets = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like "*MortalSim-Bot*" }
foreach ($p in $targets) { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
Get-ChildItem (Join-Path $root "data\*.lock") -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue

Start-Process -FilePath $python -ArgumentList "src\daemon.py" -WorkingDirectory $root -WindowStyle Hidden
Start-Sleep -Seconds 6

$daemon = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like "*MortalSim-Bot*daemon.py*" }
$bot = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
  Where-Object { $_.CommandLine -like "*MortalSim-Bot*bot.py*" }
"daemon=$($daemon.ProcessId) bot=$($bot.ProcessId)"
