$py = 'C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe'
Write-Output ('NOW=' + (Get-Date).ToString('HH:mm:ss'))
Write-Output ('procs=' + (Get-Process python -ErrorAction SilentlyContinue).Count)
$os = Get-CimInstance Win32_OperatingSystem
Write-Output ('free_ram_gb=' + [math]::Round($os.FreePhysicalMemory/1MB,2) + '  total_gb=' + [math]::Round($os.TotalVisibleMemorySize/1MB,2))
Write-Output ('commit_gb=' + [math]::Round(($os.TotalVirtualMemorySize - $os.FreeVirtualMemory)/1MB,2))
Write-Output '--- per-process CPU (seconds) and RSS (MB) ---'
Get-Process python -ErrorAction SilentlyContinue | Sort-Object -Property CPU -Descending | ForEach-Object {
    Write-Output ($_.Id.ToString().PadRight(8) + ' cpu_s=' + [math]::Round($_.CPU,1).ToString().PadLeft(8) + '  rss_mb=' + [math]::Round($_.WorkingSet64/1MB,0).ToString().PadLeft(5) + '  start=' + $_.StartTime.ToString('HH:mm:ss'))
}
Write-Output '--- pool.log tail 6 ---'
Get-Content C:\arena\pool.log -Tail 6 -Encoding UTF8
Write-Output '--- pool_stderr tail 5 ---'
Get-Content C:\arena\pool_stderr.log -Tail 5 -Encoding UTF8 -ErrorAction SilentlyContinue
Write-Output '--- log mtime age ---'
$li = Get-Item C:\arena\pool.log
Write-Output ('pool.log last write: ' + $li.LastWriteTime.ToString('HH:mm:ss'))
