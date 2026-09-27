$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File C:\arena\arena_daemon.ps1'
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3
Register-ScheduledTask -TaskName 'AtozukeMahjongArena' -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Enable-ScheduledTask -TaskName 'AtozukeMahjongArena' | Out-Null
Start-ScheduledTask -TaskName 'AtozukeMahjongArena'
Start-Sleep -Seconds 25
Write-Output "task state: $((Get-ScheduledTask -TaskName 'AtozukeMahjongArena').State)"
Write-Output "python procs: $((Get-Process python -ErrorAction SilentlyContinue).Count)"
Get-Content 'C:\arena\v3_exit.txt' -ErrorAction SilentlyContinue -Tail 4
Get-Content 'C:\arena\v3_stdout.log' -ErrorAction SilentlyContinue -Tail 6
