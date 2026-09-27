Write-Output ("now=" + (Get-Date -Format "HH:mm:ss"))
Write-Output "--- 最近完成批次（原生 ONNX 生产配置）---"
Get-Content "C:\arena\v4_stdout.log" | Select-String "s/" | Select-Object -Last 10 | ForEach-Object { $_.Line }
Get-Content "C:\arena\db_out.txt" -ErrorAction SilentlyContinue
Start-Process -FilePath "C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe" -ArgumentList "C:/arena/db_probe.py" -Wait -NoNewWindow -RedirectStandardOutput "C:\arena\db_out.txt"
Get-Content "C:\arena\db_out.txt"
Write-Output ("procs=" + (Get-Process python -ErrorAction SilentlyContinue).Count + " cpu=" + [math]::Round((Get-Counter "\Processor(_Total)\% Processor Time").CounterSamples.CookedValue,1))
