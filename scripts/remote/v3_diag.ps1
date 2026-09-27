Write-Output "=== v3_stderr.log (tail 40) ==="
Get-Content 'C:\arena\v3_stderr.log' -ErrorAction SilentlyContinue -Tail 40
Write-Output "=== v3_stdout.log (tail 15) ==="
Get-Content 'C:\arena\v3_stdout.log' -ErrorAction SilentlyContinue -Tail 15
Write-Output "=== arena.log (tail 15) ==="
Get-Content 'C:\arena\arena.log' -ErrorAction SilentlyContinue -Tail 15
Write-Output "=== 日志目录中新生成的 gz 数量 ==="
(Get-ChildItem 'C:\arena\logs\1v3_consensus_v3_vs_ext_mortal' -Filter *.gz -ErrorAction SilentlyContinue).Count
Write-Output "=== 内存 ==="
(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory
