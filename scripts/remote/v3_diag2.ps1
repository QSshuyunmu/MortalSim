Write-Output "=== 最近 25 分钟应用日志中与 python 相关的错误 ==="
Get-WinEvent -FilterHashtable @{LogName='Application'; StartTime=(Get-Date).AddMinutes(-25)} -ErrorAction SilentlyContinue |
  Where-Object { $_.Message -match 'python' } |
  Select-Object -First 4 TimeCreated, Id, ProviderName, @{n='Msg';e={$_.Message.Substring(0, [Math]::Min(300, $_.Message.Length))}} |
  Format-List | Out-String -Width 200
Write-Output "=== 守护任务状态 ==="
Get-ScheduledTask -TaskName 'AtozukeMahjongArena' -ErrorAction SilentlyContinue | Select-Object TaskName, State | Format-Table -AutoSize | Out-String
Write-Output "=== 是否有 arena_daemon 进程 ==="
(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.CommandLine -like '*arena_daemon*' } | Measure-Object).Count
