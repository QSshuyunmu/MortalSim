Write-Output "--- v4 exit log ---"
Get-Content "C:\arena\v4_exit.txt" -ErrorAction SilentlyContinue -Tail 3
Write-Output "--- v4 stdout tail ---"
Get-Content "C:\arena\v4_stdout.log" -ErrorAction SilentlyContinue -Tail 8
Write-Output "--- v4 stderr tail ---"
Get-Content "C:\arena\v4_stderr.log" -ErrorAction SilentlyContinue -Tail 6
Write-Output "--- procs / CPU ---"
(Get-Process python -ErrorAction SilentlyContinue).Count
(Get-Counter "\Processor(_Total)\% Processor Time").CounterSamples.CookedValue
Write-Output "--- DB ---"
Start-Process -FilePath "C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe" -ArgumentList "C:/arena/db_probe.py" -Wait -NoNewWindow -RedirectStandardOutput "C:\arena\db_out.txt"
Get-Content "C:\arena\db_out.txt"
