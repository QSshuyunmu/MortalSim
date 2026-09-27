Write-Output "--- exit log ---"
Get-Content 'C:\arena\v3_exit.txt' -ErrorAction SilentlyContinue -Tail 6
Write-Output "--- stdout tail ---"
Get-Content 'C:\arena\v3_stdout.log' -ErrorAction SilentlyContinue -Tail 6
Write-Output "--- stderr tail ---"
Get-Content 'C:\arena\v3_stderr.log' -ErrorAction SilentlyContinue -Tail 8
Write-Output "--- procs / CPU ---"
(Get-Process python -ErrorAction SilentlyContinue).Count
(Get-Counter '\Processor(_Total)\% Processor Time').CounterSamples.CookedValue
