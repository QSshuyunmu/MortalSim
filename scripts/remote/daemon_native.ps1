$ErrorActionPreference = "Continue"
$py = "C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe"
Set-Location "C:\arena"
$env:ORT_DYLIB_PATH = "C:\arena\onnxruntime.dll"
$n = 0
while ($true) {
    $n++
    "[$(Get-Date -Format yyyy-MM-dd HH:mm:ss)] [Guardian] launch #$n (V4 NATIVE onnx batch=4 conc=5 thr=3)" | Add-Content "C:\arena\v4_exit.txt"
    $p = Start-Process -FilePath $py -ArgumentList "C:\arena\arena_coordinator_v4.py","--engine","native","--batch-seeds","4","--concurrency","5","--threads","3" -WorkingDirectory "C:\arena" -RedirectStandardOutput "C:\arena\v4_stdout.log" -RedirectStandardError "C:\arena\v4_stderr.log" -PassThru -WindowStyle Hidden
    $p.WaitForExit()
    "[$(Get-Date -Format yyyy-MM-dd HH:mm:ss)] [Guardian] exit=$($p.ExitCode)" | Add-Content "C:\arena\v4_exit.txt"
    Start-Sleep -Seconds 10
}
