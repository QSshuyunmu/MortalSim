Write-Output ("now=" + (Get-Date -Format "HH:mm:ss"))
Write-Output ("procs=" + (Get-Process python -ErrorAction SilentlyContinue).Count)
Get-Content C:\arena\pool_stdout.log -Tail 14
Write-Output "--- plan block1 ---"
Get-Content C:\arena\pool_plan.json -ErrorAction SilentlyContinue | Select-String "\"1\"" -Context 0,12 | Select-Object -First 1
