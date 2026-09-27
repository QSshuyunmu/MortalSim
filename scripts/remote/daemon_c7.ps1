$ErrorActionPreference = "Continue"
$py = "C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe"
Set-Location "C:\arena"
$n = 0
while ($true) {
    $n++
    "[$(Get-Date -Format yyyy-MM-dd HH:mm:ss)] [PoolGuardian] launch #$n (4P conc=7 thr=2 block=1)" | Add-Content "C:\arena\pool_exit.txt"
    $p = Start-Process -FilePath $py -ArgumentList "C:\arena\pool_arena.py","--batch-seeds","4","--concurrency","7","--threads","2","--start-block","1" -WorkingDirectory "C:\arena" -RedirectStandardOutput "C:\arena\pool_stdout.log" -RedirectStandardError "C:\arena\pool_stderr.log" -PassThru -WindowStyle Hidden
    $p.WaitForExit()
    "[$(Get-Date -Format yyyy-MM-dd HH:mm:ss)] [PoolGuardian] exit=$($p.ExitCode)" | Add-Content "C:\arena\pool_exit.txt"
    Start-Sleep -Seconds 15
}
