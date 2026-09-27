# Skip when the STOP switch is present: the pool is intentionally down.
if (Test-Path 'C:\arena\STOP') {
    Write-Output "STOP file present - skip restart"
    exit 0
}
Stop-ScheduledTask -TaskName 'AtozukeMahjongArena' -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
taskkill /F /IM python.exe 2>&1 | Out-Null
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.CommandLine -like '*arena_daemon*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Seconds 3
Start-ScheduledTask -TaskName 'AtozukeMahjongArena'
Start-Sleep -Seconds 25
Write-Output "python procs: $((Get-Process python -ErrorAction SilentlyContinue).Count)"
Get-Content 'C:\arena\pool_exit.txt' -ErrorAction SilentlyContinue -Tail 4
Get-Content 'C:\arena\pool_stdout.log' -ErrorAction SilentlyContinue -Tail 5
