Write-Output ("now=" + (Get-Date -Format "HH:mm:ss"))
Write-Output ("prod pyd = " + (Get-Item C:\arena\libriichi.pyd).Length)
Write-Output ("pool models = " + ((Get-ChildItem C:\arena\models\tsypx\*.pth).Name -join ", "))
Write-Output ("procs = " + (Get-Process python -ErrorAction SilentlyContinue).Count)
Write-Output "--- pool_exit ---"
Get-Content C:\arena\pool_exit.txt -Tail 3 -ErrorAction SilentlyContinue
Write-Output "--- pool_stdout tail ---"
Get-Content C:\arena\pool_stdout.log -Tail 12 -ErrorAction SilentlyContinue
Write-Output "--- pool_stderr tail ---"
Get-Content C:\arena\pool_stderr.log -Tail 6 -ErrorAction SilentlyContinue
Write-Output "--- pool.log tail ---"
Get-Content C:\arena\pool.log -Tail 10 -ErrorAction SilentlyContinue
