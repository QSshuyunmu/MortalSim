$ErrorActionPreference = "Continue"
Stop-ScheduledTask -TaskName "AtozukeMahjongArena" -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name=powershell.exe" | Where-Object { $_.CommandLine -like "*arena_daemon*" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
taskkill /F /IM python.exe 2>&1 | Out-Null
Start-Sleep -Seconds 5
Copy-Item -Force C:\arena\libriichi_new.dll C:\arena\libriichi.pyd
Write-Output ("pyd now = " + (Get-Item C:\arena\libriichi.pyd).Length)
Start-ScheduledTask -TaskName "AtozukeMahjongArena"
Start-Sleep -Seconds 30
Write-Output ("procs = " + (Get-Process python -ErrorAction SilentlyContinue).Count)
Get-Content C:\arena\pool_stdout.log -Tail 6
Get-Content C:\arena\pool_stderr.log -Tail 4
