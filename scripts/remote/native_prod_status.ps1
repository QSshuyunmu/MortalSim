Write-Output ("now=" + (Get-Date -Format "HH:mm:ss"))
Get-Content "C:\arena\v4_stdout.log" | Select-String "s/" | Select-Object -Last 6 | ForEach-Object { $_.Line }
Write-Output "--- stderr ---"
Get-Content "C:\arena\v4_stderr.log" -Tail 3
Write-Output ("procs=" + (Get-Process python -ErrorAction SilentlyContinue).Count + " cpu=" + [math]::Round((Get-Counter "\Processor(_Total)\% Processor Time").CounterSamples.CookedValue,1))
Start-Process -FilePath "C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe" -ArgumentList "C:/arena/db_probe.py" -Wait -NoNewWindow -RedirectStandardOutput "C:\arena\db_out.txt"
Get-Content "C:\arena\db_out.txt"
