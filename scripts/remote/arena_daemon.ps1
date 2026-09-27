$py = 'C:\Users\23610\AppData\Local\Programs\Python\Python313\python.exe'
Set-Location 'C:\arena'

# --- tunables (edit here, then restart the scheduled task) ---
# conc=16 was measured WORSE than conc=8 (502 vs 576 半庄/h): 16 workers x 2 rayon threads
# = 32 threads on 18 logical cores collapsed per-task efficiency (~50 -> ~105 s/半庄).
$conc = 8           # initial concurrency
$minc = 6           # adaptive lower bound
$maxc = 10          # adaptive upper bound
$rayon = '2'        # threads per worker (RAYON/OMP/MKL)
$onnxThreads = '1'  # ONNX intra-op threads per worker (1 core per worker to prevent hyper-thread contention)
$torchThreads = '2' # passed to pool_arena.py --threads

# start block: prefer C:\arena\start_block.txt (single integer), else default 3
$sb = '3'
if (Test-Path 'C:\arena\start_block.txt') {
    $t = (Get-Content 'C:\arena\start_block.txt' -First 1).Trim()
    if ($t -match '^\d+$') { $sb = $t }
}

# publish the concurrency ceiling so the health probe can size its orphan threshold
Set-Content -Path 'C:\arena\conc_expected.txt' -Value $maxc -Encoding ascii

$env:ORT_DYLIB_PATH = 'C:\arena\onnxruntime.dll'
$env:RAYON_NUM_THREADS = $rayon
$env:OMP_NUM_THREADS = $rayon
$env:MKL_NUM_THREADS = $rayon
$env:ARENA_ONNX_THREADS = $onnxThreads
# 原生 ONNX 通路：验证通过后置 '0' 启用；'1' = 完全回退 PyTorch
$env:ARENA_NO_ONNX = '0'

while ($true) {
    # STOP switch: if present, idle here and never launch the pool (delete to resume)
    if (Test-Path 'C:\arena\STOP') {
        Start-Sleep -Seconds 30
        continue
    }
    Add-Content 'C:\arena\pool_exit.txt' -Value ((Get-Date).ToString('yyyy-MM-dd HH:mm:ss') + " launch(conc=$conc minc=$minc maxc=$maxc rayon=$rayon)")
    Start-Process -FilePath $py -ArgumentList 'C:\arena\pool_arena.py','--batch-seeds','4','--concurrency',"$conc",'--threads',$torchThreads,'--start-block',$sb,'--min-concurrency',"$minc",'--max-concurrency',"$maxc" -WorkingDirectory 'C:\arena' -RedirectStandardOutput 'C:\arena\pool_stdout.log' -RedirectStandardError 'C:\arena\pool_stderr.log' -Wait -WindowStyle Hidden
    Add-Content 'C:\arena\pool_exit.txt' -Value ((Get-Date).ToString('yyyy-MM-dd HH:mm:ss') + ' exited, respawn in 15s')
    Start-Sleep -Seconds 15
}
