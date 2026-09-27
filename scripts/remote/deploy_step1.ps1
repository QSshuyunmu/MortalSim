Get-ScheduledTask -TaskName 'AtozukeMahjongArena' -ErrorAction SilentlyContinue | Disable-ScheduledTask -ErrorAction SilentlyContinue | Out-Null
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.CommandLine -like '*arena_daemon*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
taskkill /F /IM python.exe 2>&1 | Out-Null
Start-Sleep -Seconds 2
Write-Output "step1 done: guardian disabled, python killed"
