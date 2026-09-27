# 远端守护：Atozuke 四卓分层天梯（镜像 daemon_pool.ps1 的守护模式）
# - 进程崩溃后 15 秒自动重启（另有计划任务 AtozukeLadderArena 开机拉起本脚本）
# - 天梯自身通过 C:\arena\LADDER_STOP 停机文件优雅退出（跑完当前批并存档）
$ErrorActionPreference = "Continue"
$py = "C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe"
Set-Location "C:\arena\ladder"

# 引擎线程配置：18 逻辑核；ONNX intra=1（生产同款），PyTorch intra=3，rayon=2
$env:ARENA_ONNX_THREADS = "1"
$env:LADDER_TORCH_THREADS = "3"
$env:RAYON_NUM_THREADS = "2"

$n = 0
while ($true) {
    $n++
    # Single-instance guard: never launch if a ladder runner is already alive.
    $existing = Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.CommandLine -like "*ladder_arena_atozuke*" }
    if ($existing) {
        "[$(Get-Date -Format yyyy-MM-dd HH:mm:ss)] [LadderGuardian] runner already alive, skip launch #$n" | Add-Content "C:/arena/ladder/ladder_exit.txt"
        Start-Sleep -Seconds 60
        continue
    }
    "[$(Get-Date -Format yyyy-MM-dd HH:mm:ss)] [LadderGuardian] launch #$n (batch=16 tables_total=6 onnx_intra=1)" | Add-Content "C:\arena\ladder\ladder_exit.txt"
    $p = Start-Process -FilePath $py -ArgumentList "-X","utf8","C:\arena\ladder\ladder_arena_atozuke.py","--batch-seeds","16","--tables-total","6" -WorkingDirectory "C:\arena\ladder" -RedirectStandardOutput "C:\arena\ladder\ladder_stdout.log" -RedirectStandardError "C:\arena\ladder\ladder_stderr.log" -PassThru -WindowStyle Hidden
    $p.WaitForExit()
    "[$(Get-Date -Format yyyy-MM-dd HH:mm:ss)] [LadderGuardian] exit=$($p.ExitCode)" | Add-Content "C:\arena\ladder\ladder_exit.txt"
    Start-Sleep -Seconds 15
}
