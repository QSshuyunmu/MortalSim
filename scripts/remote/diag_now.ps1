Write-Output ('NOW=' + (Get-Date).ToString('HH:mm:ss'))
Write-Output '--- all python processes ---'
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | ForEach-Object {
    $pr = Get-Process -Id $_.ProcessId -ErrorAction SilentlyContinue
    $cmd = $_.CommandLine
    if ($cmd.Length -gt 150) { $cmd = $cmd.Substring(0, 150) }
    Write-Output ($_.ProcessId.ToString().PadRight(7) + $_.CreationDate.ToString('HH:mm:ss') + '  cpu_s=' + [math]::Round($pr.CPU,0).ToString().PadLeft(6) + '  ' + $cmd)
}
Write-Output '--- pool.log tail 5 ---'
Get-Content C:\arena\pool.log -Tail 5 -Encoding UTF8
Write-Output '--- health_task.log tail 6 ---'
Get-Content C:\arena\health_task.log -Tail 6 -Encoding UTF8 -ErrorAction SilentlyContinue
Write-Output '--- health_actions.log tail 3 ---'
Get-Content C:\arena\health_actions.log -Tail 3 -Encoding UTF8 -ErrorAction SilentlyContinue
Write-Output '--- pool_exit tail 4 ---'
Get-Content C:\arena\pool_exit.txt -Tail 4
