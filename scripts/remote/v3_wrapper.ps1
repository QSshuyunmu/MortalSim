$ErrorActionPreference = 'Continue'
$py = 'C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe'
Set-Location 'C:\arena'
$n = 0
while ($true) {
    $n++
    "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] launch #$n" | Add-Content 'C:\arena\v3_exit.txt'
    $p = Start-Process -FilePath $py `
        -ArgumentList 'C:\arena\arena_coordinator_v3.py','--mode','1v3','--batch-seeds','4','--concurrency','3','--threads','4' `
        -WorkingDirectory 'C:\arena' -RedirectStandardOutput 'C:\arena\v3_stdout.log' `
        -RedirectStandardError 'C:\arena\v3_stderr.log' -PassThru -WindowStyle Hidden
    $p.WaitForExit()
    "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] exit code = $($p.ExitCode)" | Add-Content 'C:\arena\v3_exit.txt'
    Start-Sleep -Seconds 5
}
