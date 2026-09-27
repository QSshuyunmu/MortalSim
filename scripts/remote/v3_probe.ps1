Write-Output "--- v3 stdout tail ---"
Get-Content 'C:\arena\v3_stdout.log' -ErrorAction SilentlyContinue -Tail 10
Write-Output "--- python procs ---"
(Get-Process python -ErrorAction SilentlyContinue).Count
Write-Output "--- CPU% ---"
(Get-Counter '\Processor(_Total)\% Processor Time').CounterSamples.CookedValue
