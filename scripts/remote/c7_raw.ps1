Write-Output ("now=" + (Get-Date -Format "HH:mm:ss"))
Get-Content "C:\arena\v3_stdout.log" -Tail 6
Get-Content "C:\arena\v3_stderr.log" -Tail 4
Start-Process -FilePath "C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe" -ArgumentList "C:/arena/db_probe.py" -Wait -NoNewWindow -RedirectStandardOutput "C:\arena\db_out.txt"
Get-Content "C:\arena\db_out.txt"
